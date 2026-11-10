"""Keep a local OmniRoute worker alive and drain the shared Supabase queue."""

import os
import socket
import threading
import time
import uuid
from pathlib import Path

from run import (
    main,
    release_video_lease,
    renew_video_lease,
    required_env,
    split_env_list,
    supabase_api_key,
    try_acquire_video_lease,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_local_env():
    """Load simple KEY=value entries from .env.local without replacing process env."""
    path = Path(os.getenv("LOCAL_WORKER_ENV_FILE", PROJECT_ROOT / ".env.local"))
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        raise RuntimeError(f"Local settings file is missing: {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if name and name not in os.environ:
            os.environ[name] = value


def main_loop():
    load_local_env()
    os.environ["RUN_MODE"] = "process"
    # This worker must never fall back to Gemini, even if a developer has that
    # variable set in their shell environment.
    os.environ["AI_PROVIDER"] = "omniroute"
    os.environ.setdefault("OMNIROUTE_BASE_URL", "http://127.0.0.1:20128/v1")
    required_env("SUPABASE_URL")
    supabase_api_key()
    required_env("OMNIROUTE_API_KEY")
    required_env("YOUTUBE_API_KEY")
    if not split_env_list("OMNIROUTE_MODELS", "OMNIROUTE_MODEL"):
        raise RuntimeError("Set OMNIROUTE_MODELS (or OMNIROUTE_MODEL) in .env.local")

    lease_seconds = int(os.getenv("VIDEO_WORKER_LEASE_SECONDS", "180"))
    heartbeat_seconds = int(os.getenv("VIDEO_WORKER_HEARTBEAT_SECONDS", "30"))
    poll_seconds = int(os.getenv("VIDEO_WORKER_POLL_SECONDS", "60"))
    discovery_interval = int(os.getenv("LOCAL_DISCOVERY_INTERVAL_SECONDS", "3600"))
    os.environ.setdefault("DISCOVERY_LIMIT", "50")
    if discovery_interval < 60:
        raise ValueError("LOCAL_DISCOVERY_INTERVAL_SECONDS must be at least 60")
    if heartbeat_seconds < 5 or heartbeat_seconds >= lease_seconds:
        raise ValueError("VIDEO_WORKER_HEARTBEAT_SECONDS must be at least 5 and less than the lease duration")
    if poll_seconds < 5:
        raise ValueError("VIDEO_WORKER_POLL_SECONDS must be at least 5")

    owner_id = f"local-{socket.gethostname()}-{uuid.uuid4().hex[:12]}"
    os.environ["VIDEO_WORKER_ID"] = owner_id
    os.environ["VIDEO_WORKER_LEASE_HELD"] = "true"
    os.environ["VIDEO_WORKER_LEASE_SECONDS"] = str(lease_seconds)

    print(f"Local queue worker started as {owner_id}")
    print(f"Provider: OmniRoute; poll interval: {poll_seconds}s")
    print(f"Local channel discovery interval: {discovery_interval}s")

    while True:
        try:
            if try_acquire_video_lease(owner_id, lease_seconds):
                break
            print("Another worker currently owns the queue; waiting...")
        except Exception as exc:
            print(f"Could not acquire the Supabase worker lease; retrying: {exc}")
        time.sleep(poll_seconds)

    stopping = threading.Event()
    lost_lease = threading.Event()

    def keep_lease_alive():
        while not stopping.wait(heartbeat_seconds):
            try:
                if not renew_video_lease(owner_id, lease_seconds):
                    lost_lease.set()
                    print("Local worker lost its queue lease; pausing processing until it can reacquire it.")
                    while not stopping.wait(poll_seconds):
                        try:
                            if try_acquire_video_lease(owner_id, lease_seconds):
                                lost_lease.clear()
                                print("Local worker reacquired the queue lease.")
                                break
                        except Exception as exc:
                            print(f"Could not reacquire the Supabase worker lease: {exc}")
            except Exception as exc:
                lost_lease.set()
                print(f"Could not renew the Supabase worker lease; pausing until it is reacquired: {exc}")
                while not stopping.wait(poll_seconds):
                    try:
                        if try_acquire_video_lease(owner_id, lease_seconds):
                            lost_lease.clear()
                            print("Local worker reacquired the queue lease.")
                            break
                    except Exception as retry_exc:
                        print(f"Could not reacquire the Supabase worker lease: {retry_exc}")

    heartbeat = threading.Thread(target=keep_lease_alive, name="queue-lease-heartbeat", daemon=True)
    heartbeat.start()
    next_discovery = 0
    try:
        while True:
            if lost_lease.is_set():
                time.sleep(poll_seconds)
                continue
            try:
                if time.monotonic() >= next_discovery:
                    os.environ["RUN_MODE"] = "discover"
                    main()
                    next_discovery = time.monotonic() + discovery_interval
                os.environ["RUN_MODE"] = "process"
                main()
            except SystemExit as exc:
                if exc.code not in (None, 0):
                    print(f"Processing pass ended with status {exc.code}; it will retry next pass.")
            except Exception as exc:
                print(f"Processing pass failed; it will retry next pass: {exc}")
            time.sleep(poll_seconds)
    except KeyboardInterrupt:
        print("Stopping local queue worker...")
    finally:
        stopping.set()
        heartbeat.join(timeout=heartbeat_seconds + 2)
        release_video_lease(owner_id)


if __name__ == "__main__":
    main_loop()
