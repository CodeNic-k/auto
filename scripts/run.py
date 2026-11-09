"""Find websites and useful notes in public YouTube Shorts."""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from google import genai
from google.genai import types
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


CATEGORIES = {
    "AI tools", "Productivity", "Design", "Dev tools", "Privacy/Security",
    "Free resources", "Learning", "Entertainment", "Other",
}
CATEGORY_TEXT = (
    "AI tools, Productivity, Design, Dev tools, Privacy/Security, Free resources, "
    "Learning, Entertainment, Other"
)
PROMPT = f"""
Review this YouTube video and return ONLY one JSON object with this exact shape:
{{
  "websites": [{{"url": "...", "description": "...", "category": "..."}}],
  "notes_eligible": true,
  "notes": [{{"title": "...", "detail": "...", "category": "..."}}]
}}

WEBSITES: list every website URL or domain actually shown or spoken. Do not guess.
Use categories only from: {CATEGORY_TEXT}. Return [] if none.

NOTES: save short, useful tips or techniques that the video teaches and a viewer could
use. If the video mainly demonstrates, reviews, or recommends a website/app/service to
send viewers to it, set notes_eligible to false and notes to []. Do not turn a website
name, URL, or description of what a site does into a tip. For other videos with no useful
tip, use notes: []. Use the same category list: {CATEGORY_TEXT}.
""".strip()
NOTES_PROMPT = f"""
Extract useful tips or techniques this video teaches. Return ONLY one JSON object:
{{"notes_eligible": true, "notes": [{{"title": "...", "detail": "...", "category": "..."}}]}}

If this video mainly demonstrates, reviews, or recommends a website/app/service to send
viewers to it, set notes_eligible to false and notes to []. Do not turn a website name,
URL, or description of what a site does into a tip. If there is no useful transferable
tip, return notes: []. Allowed categories: {CATEGORY_TEXT}.
""".strip()
TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "dclid", "yclid", "mc_cid", "mc_eid")


class RateLimited(Exception):
    """Raised when every configured Gemini model/key combination is rate limited."""


def split_env_list(name, fallback_name=None):
    """Read a comma- or newline-separated Actions variable/secret."""
    raw = os.getenv(name, "")
    if not raw and fallback_name:
        raw = os.getenv(fallback_name, "")
    return list(dict.fromkeys(item.strip() for item in re.split(r"[,\r\n]+", raw)
                              if item.strip()))


def required_env(name):
    # GitHub Secrets can accidentally include a copied newline or spaces.
    # Trim those so they cannot corrupt URLs, headers, or model path segments.
    value = (os.getenv(name) or "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def supabase_request(method, table, *, params=None, body=None, prefer=None):
    """Make one PostgREST request using the private service key."""
    base_url = required_env("SUPABASE_URL").rstrip("/")
    service_key = required_env("SUPABASE_SERVICE_KEY")
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    response = requests.request(
        method,
        f"{base_url}/rest/v1/{table}",
        params=params,
        json=body,
        headers=headers,
        timeout=30,
    )
    if not response.ok:
        # Include PostgREST's message (for example, "table not found") in the
        # Actions log so setup problems are diagnosable without exposing keys.
        detail = response.text[:1000].strip()
        raise RuntimeError(
            f"Supabase {method} {table} failed with HTTP {response.status_code}: "
            f"{detail or response.reason}"
        )
    if not response.content:
        return []
    return response.json()


def read_handles():
    """Read non-empty handles, ignoring comments and optional leading @ signs."""
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "channels.txt")
    if not os.path.exists(path):
        raise RuntimeError(f"channels.txt was not found at {path}")
    handles = []
    with open(path, encoding="utf-8") as file:
        for line in file:
            handle = line.split("#", 1)[0].strip().lstrip("@")
            if handle and handle not in handles:
                handles.append(handle)
    if not handles:
        raise RuntimeError("channels.txt has no channel handles; add one per line")
    return handles


def youtube_call(request):
    """Run a YouTube API request and explain quota/permission failures plainly."""
    try:
        return request.execute()
    except HttpError as exc:
        raise RuntimeError(f"YouTube API error: {exc}") from exc


def channel_details(youtube, handle):
    result = youtube_call(youtube.channels().list(part="id,contentDetails", forHandle=handle))
    items = result.get("items", [])
    if not items:
        raise RuntimeError(f"YouTube did not find channel @{handle}")
    item = items[0]
    return item["id"], item["contentDetails"]["relatedPlaylists"]["uploads"]


def upsert_channel(handle, channel_id, playlist_id):
    supabase_request(
        "POST", "channels", params={"on_conflict": "handle"},
        body={"handle": handle, "channel_id": channel_id,
              "uploads_playlist_id": playlist_id},
        prefer="resolution=merge-duplicates,return=minimal",
    )


def discover_playlist(youtube, handle, playlist_id, max_videos=0):
    """Page through a channel's entire uploads playlist; add unseen videos."""
    page_token = None
    discovered = 0
    scanned = 0
    while True:
        page_size = 50 if not max_videos else min(50, max_videos - scanned)
        if page_size <= 0:
            break
        result = youtube_call(youtube.playlistItems().list(
            part="snippet,contentDetails", playlistId=playlist_id,
            maxResults=page_size, pageToken=page_token,
        ))
        scanned += len(result.get("items", []))
        rows = []
        for item in result.get("items", []):
            video_id = item.get("contentDetails", {}).get("videoId")
            if not video_id:
                continue
            title = item.get("snippet", {}).get("title", "")
            rows.append({"video_id": video_id, "channel_handle": handle,
                         "title": title, "status": "pending"})
        if rows:
            # Ignore conflicts so rerunning never resets a video's existing status.
            supabase_request(
                "POST", "videos", params={"on_conflict": "video_id"}, body=rows,
                prefer="resolution=ignore-duplicates,return=minimal",
            )
            discovered += len(rows)
        page_token = result.get("nextPageToken")
        if not page_token or (max_videos and scanned >= max_videos):
            break
    return discovered


def pending_videos_without_duration(handle):
    return supabase_request(
        "GET", "videos",
        params={"select": "video_id", "channel_handle": f"eq.{handle}",
                "status": "eq.pending", "duration_seconds": "is.null", "limit": "1000"},
    )


def update_video(video_id, fields):
    supabase_request(
        "PATCH", "videos", params={"video_id": f"eq.{video_id}"},
        body=fields, prefer="return=minimal",
    )


def iso_duration_seconds(value):
    """Convert the YouTube API's ISO 8601 duration (for example PT1M20S)."""
    match = re.fullmatch(r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if not match:
        raise ValueError(f"Unrecognized YouTube duration: {value}")
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def fill_durations(youtube, handle):
    """Fetch duration details in YouTube's maximum 50-ID batches."""
    pending = pending_videos_without_duration(handle)
    video_ids = [row["video_id"] for row in pending]
    for start in range(0, len(video_ids), 50):
        batch = video_ids[start:start + 50]
        result = youtube_call(youtube.videos().list(
            part="contentDetails", id=",".join(batch), maxResults=50,
        ))
        for item in result.get("items", []):
            video_id = item["id"]
            try:
                seconds = iso_duration_seconds(item["contentDetails"]["duration"])
                update_video(video_id, {
                    "duration_seconds": seconds,
                    # YouTube's API exposes duration, not a reliable Shorts flag.
                    "is_short": seconds <= 180,
                })
            except Exception as exc:
                print(f"Could not save duration for {video_id}: {exc}")


def get_pending_shorts(batch_size):
    if batch_size < 1:
        raise ValueError("BATCH_SIZE must be at least 1")
    return supabase_request(
        "GET", "videos", params={
            "select": "video_id,channel_handle,title,duration_seconds",
            "status": "eq.pending", "is_short": "eq.true",
            "order": "video_id.asc", "limit": str(batch_size),
        },
    )


def get_pending_notes(limit):
    """Find previously link-processed Shorts that still need note analysis."""
    if limit < 1:
        return []
    return supabase_request(
        "GET", "videos", params={
            "select": "video_id,channel_handle,title,duration_seconds",
            "status": "neq.pending", "notes_status": "eq.pending",
            "is_short": "eq.true", "order": "video_id.asc", "limit": str(limit),
        },
    )


def get_response_text(response):
    text = getattr(response, "text", None)
    if text:
        return text
    raise ValueError("Gemini returned an empty response")


def parse_gemini_json(text):
    text = text.strip()
    # Tolerate markdown code fences even though the prompt requests plain JSON.
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Gemini response must be a JSON object")
    if not isinstance(data.get("websites", []), list):
        raise ValueError("Gemini websites field must be a JSON array")
    if not isinstance(data.get("notes", []), list):
        raise ValueError("Gemini notes field must be a JSON array")
    if "notes_eligible" in data and not isinstance(data["notes_eligible"], bool):
        raise ValueError("Gemini notes_eligible field must be true or false")
    return data


def normalize_url(raw_url):
    if not isinstance(raw_url, str):
        raise ValueError("Each result's url must be text")
    raw_url = raw_url.strip().strip(".,;:!?)\\\"'<>]")
    if not raw_url:
        raise ValueError("URL is empty")
    if not re.match(r"^[a-z][a-z0-9+.-]*://", raw_url, re.IGNORECASE):
        raw_url = "https://" + raw_url
    parts = urlsplit(raw_url)
    if not parts.hostname:
        raise ValueError(f"URL has no hostname: {raw_url}")
    host = parts.hostname.encode("idna").decode("ascii").lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if parts.port:
        host = f"{host}:{parts.port}"
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith(TRACKING_PREFIXES):
            continue
        query.append((key, value))
    cleaned = urlunsplit((parts.scheme.lower(), host, parts.path.rstrip("/"),
                          urlencode(query, doseq=True), ""))
    return cleaned, parts.hostname.lower()


def gemini_call(clients, models, video_id, *, notes_only=False):
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    prompt = NOTES_PROMPT if notes_only else PROMPT
    errors = []
    for model in models:
        for client_index, client in enumerate(clients, start=1):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=[
                        types.Part(file_data=types.FileData(file_uri=video_url)),
                        types.Part(text=prompt),
                    ],
                    config=types.GenerateContentConfig(temperature=0),
                )
                return parse_gemini_json(get_response_text(response))
            except Exception as exc:
                status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
                message = str(exc)
                is_rate_limit = (str(status) == "429" or "429" in message
                                 or "RESOURCE_EXHAUSTED" in message)
                errors.append((model, client_index, is_rate_limit, message[:500]))
                print(f"Gemini model {model} with key slot {client_index} failed; trying fallback: {message[:300]}")

    if errors and all(item[2] for item in errors):
        raise RateLimited("All configured model/key combinations were rate limited")
    summary = "; ".join(
        f"{model} (key slot {key_index}): {message}"
        for model, key_index, _, message in errors
    )
    raise RuntimeError(f"All configured Gemini fallbacks failed: {summary}")


def save_links(video_id, results):
    rows = []
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("Each JSON array item must be an object")
        url, domain = normalize_url(result.get("url", ""))
        category = result.get("category", "Other")
        if not isinstance(category, str) or category not in CATEGORIES:
            category = "Other"
        description = result.get("description", "")
        if not isinstance(description, str):
            description = str(description)
        rows.append({"video_id": video_id, "url": url, "domain": domain,
                     "description": description.strip(), "category": category})
    if rows:
        supabase_request(
            "POST", "links", params={"on_conflict": "video_id,url"}, body=rows,
            prefer="resolution=ignore-duplicates,return=minimal",
        )
    return len(rows)


def save_notes(video_id, results):
    """Save short takeaways, ignoring duplicate titles from the same video."""
    rows = []
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("Each note must be a JSON object")
        title = result.get("title", "")
        detail = result.get("detail", "")
        category = result.get("category", "Other")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Each note needs a non-empty title")
        if not isinstance(detail, str) or not detail.strip():
            raise ValueError("Each note needs a non-empty detail")
        if not isinstance(category, str) or category not in CATEGORIES:
            category = "Other"
        rows.append({"video_id": video_id, "title": title.strip(),
                     "detail": detail.strip(), "category": category})
    if rows:
        supabase_request(
            "POST", "notes", params={"on_conflict": "video_id,title"}, body=rows,
            prefer="resolution=ignore-duplicates,return=minimal",
        )
    return len(rows)


def mark_failed(video_id, error):
    try:
        update_video(video_id, {"status": "failed", "error_message": str(error)[:2000],
                                "processed_at": datetime.now(timezone.utc).isoformat(),
                                "notes_status": "failed",
                                "notes_error_message": str(error)[:2000]})
    except Exception as save_error:
        print(f"Could not record failure for {video_id}: {save_error}")


def mark_notes_failed(video_id, error):
    try:
        update_video(video_id, {
            "notes_status": "failed", "notes_error_message": str(error)[:2000],
            "notes_processed_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as save_error:
        print(f"Could not record notes failure for {video_id}: {save_error}")


def main():
    mode = (os.getenv("RUN_MODE") or "all").strip().lower()
    if mode not in {"all", "discover", "process"}:
        raise ValueError("RUN_MODE must be 'discover', 'process', or 'all'")
    # Check Supabase secrets before spending API quota.
    required_env("SUPABASE_URL")
    required_env("SUPABASE_SERVICE_KEY")

    discovered_count = 0
    channel_errors = 0
    if mode in {"all", "discover"}:
        youtube_key = required_env("YOUTUBE_API_KEY")
        youtube = build("youtube", "v3", developerKey=youtube_key, cache_discovery=False)
        handles = read_handles()
        discovery_limit = int(os.getenv("DISCOVERY_LIMIT", "0"))
        if discovery_limit < 0:
            raise ValueError("DISCOVERY_LIMIT must be 0 (no limit) or a positive number")

        for handle in handles:
            try:
                channel_id, playlist_id = channel_details(youtube, handle)
                upsert_channel(handle, channel_id, playlist_id)
                discovered_count += discover_playlist(
                    youtube, handle, playlist_id, max_videos=discovery_limit
                )
                fill_durations(youtube, handle)
            except Exception as exc:
                channel_errors += 1
                print(f"Channel @{handle} could not be scanned: {exc}")

    if mode == "discover":
        print("\nDiscovery summary")
        print(f"New video rows added: {discovered_count}")
        print(f"Channel scan failures: {channel_errors}")
        if channel_errors:
            sys.exit(1)
        return

    gemini_keys = split_env_list("GEMINI_API_KEYS", "GEMINI_API_KEY")
    if not gemini_keys:
        raise RuntimeError("Missing required environment variable: GEMINI_API_KEYS (or GEMINI_API_KEY)")
    models = split_env_list("GEMINI_MODELS", "GEMINI_MODEL")
    if not models:
        raise RuntimeError("Missing required environment variable: GEMINI_MODELS (or GEMINI_MODEL)")
    gemini_clients = [genai.Client(api_key=key) for key in gemini_keys]

    batch_size = int(os.getenv("BATCH_SIZE", "5"))
    if batch_size < 1:
        raise ValueError("BATCH_SIZE must be at least 1")
    pending = get_pending_shorts(batch_size)
    calls = processed = links_found = notes_saved = failures = 0
    rate_limited = False

    def prepare_gemini_call():
        nonlocal calls
        if calls:
            time.sleep(4)
        calls += 1

    # New pending Shorts get one Gemini call that extracts links and notes together.
    for video in pending:
        video_id = video["video_id"]
        prepare_gemini_call()
        try:
            result = gemini_call(gemini_clients, models, video_id)
        except RateLimited as exc:
            print(f"Gemini rate limit reached; stopping cleanly. {exc}")
            rate_limited = True
            break
        except Exception as exc:
            failures += 1
            mark_failed(video_id, exc)
            print(f"Video {video_id} failed; continuing: {exc}")
            continue
        processed += 1

        try:
            video_links = save_links(video_id, result.get("websites", []))
            update_video(video_id, {
                "status": "done", "error_message": None,
                "processed_at": datetime.now(timezone.utc).isoformat(),
            })
            links_found += video_links
        except Exception as exc:
            failures += 1
            mark_failed(video_id, exc)
            print(f"Saving websites for {video_id} failed; continuing: {exc}")
            continue

        try:
            note_items = result.get("notes", []) if result.get("notes_eligible", True) else []
            video_notes = save_notes(video_id, note_items)
            update_video(video_id, {
                "notes_status": "done", "notes_error_message": None,
                "notes_processed_at": datetime.now(timezone.utc).isoformat(),
            })
            notes_saved += video_notes
            print(f"Done {video_id}: {video_links} website(s), {video_notes} note(s)")
        except Exception as exc:
            failures += 1
            mark_notes_failed(video_id, exc)
            print(f"Website scan done for {video_id}; saving notes failed: {exc}")

    # Backfill existing, link-processed Shorts without reprocessing their links.
    remaining = batch_size - calls
    if remaining > 0 and not rate_limited:
        old_notes = get_pending_notes(remaining)
        for video in old_notes:
            video_id = video["video_id"]
            prepare_gemini_call()
            try:
                result = gemini_call(gemini_clients, models, video_id, notes_only=True)
            except RateLimited as exc:
                print(f"Gemini rate limit reached; stopping cleanly. {exc}")
                rate_limited = True
                break
            except Exception as exc:
                failures += 1
                mark_notes_failed(video_id, exc)
                print(f"Notes for {video_id} failed; continuing: {exc}")
                continue
            processed += 1

            try:
                note_items = result.get("notes", []) if result.get("notes_eligible", True) else []
                video_notes = save_notes(video_id, note_items)
                update_video(video_id, {
                    "notes_status": "done", "notes_error_message": None,
                    "notes_processed_at": datetime.now(timezone.utc).isoformat(),
                })
                notes_saved += video_notes
                print(f"Notes done for {video_id}: {video_notes} note(s)")
            except Exception as exc:
                failures += 1
                mark_notes_failed(video_id, exc)
                print(f"Saving notes for {video_id} failed; continuing: {exc}")

    print("\nRun summary")
    print(f"Upload video rows checked: {discovered_count}")
    print(f"Gemini video calls completed: {processed}")
    print(f"Website links found and saved: {links_found}")
    print(f"Notes found and saved: {notes_saved}")
    print(f"Processing failures: {failures}")
    print(f"Channel scan failures: {channel_errors}")
    # Mark the Actions run red only after all queued work has been attempted,
    # so a bad video never prevents the rest of the batch from being processed.
    if failures or channel_errors:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Run could not start: {exc}", file=sys.stderr)
        sys.exit(1)
