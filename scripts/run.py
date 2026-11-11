"""Find websites and useful notes in public YouTube Shorts."""

import atexit
import json
import os
import re
import socket
import sys
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


CATEGORIES = {
    "AI tools", "Productivity", "Design", "Dev tools", "Privacy/Security",
    "Free resources", "Learning", "Entertainment", "How-to & workflows", "Other",
}
CATEGORY_TEXT = (
    "AI tools, Productivity, Design, Dev tools, Privacy/Security, Free resources, "
    "Learning, Entertainment, How-to & workflows, Other"
)
PROMPT = f"""
Watch the full YouTube video, including spoken audio and readable on-screen text. Return
ONLY one JSON object with this exact shape:
{{
  "websites": [{{"url": "...", "search_query": null, "description": "...", "category": "..."}}],
  "notes": [{{"title": "...", "detail": "...", "category": "..."}}]
}}

WEBSITES: Capture each distinct website, page, and search that the video actually uses,
shows, or recommends. Create a separate entry for every distinct destination. Never
combine different websites into one entry, and never put one site's instructions in
another site's description. Inspect the entire video, especially browser address bars, tabs,
page headers, app/site logos, visible text, QR codes, spoken site names, and call-to-action
instructions. A complete URL is NOT required: if a hostname or domain is readable, save
that host as a usable HTTPS URL even if the page path is hidden or cut off. If a URL is
partially visible, preserve the readable hostname and path; do not discard the site just
because part of the address is obscured. If a clearly identifiable service is named or
shown but its address is not visible, include its official homepage only when you know
the official domain with high confidence. Never invent a deep link or guess an uncertain
domain. Do not return an empty websites array merely because no full URL was spoken aloud.

For Google searches, save a query only when the video clearly demonstrates that search
(the exact query is visibly entered/submitted or its results are actively used) or the
creator explicitly tells viewers to search that exact query. Copy the exact readable query
into search_query and make url a direct Google search URL for it. Never invent a query by
turning words from narration or unrelated on-screen text into a search. Ignore incidental
background tabs, joke searches, and unrelated queries unless the creator deliberately
uses them as part of the video's point or demonstration. Do not save a bare Google homepage
just because Google appears on screen. If the query is unreadable, do not make one up.
Keep distinct demonstrated queries as separate entries, but include a repeated query once.
If a Google search is only navigation to a separately identified destination, omit the
search entry; keep it when the search itself is part of the useful workflow.

Every website description must make sense without replaying the video and must describe
only that entry's destination. Put that website's purpose, the viewer's steps, exact
inputs, and expected result in its description. This is where all instructions for using
that website belong, even when the video demonstrates a detailed workflow. For a search,
quote the exact query and explain what it is meant
to find. For ChatGPT, include the exact visible/spoken prompt or input when possible,
what task it asks ChatGPT to do, and what output the video demonstrates. For Hugging
Face, identify the shown model, Space, or resource and say what input/action produces
the demonstrated result. Use short labeled lines such as "Purpose:", "How to use it:",
and "Expected result:". If a detail is unreadable or not stated, say so briefly instead
of filling it in. Do not write generic descriptions such as "AI tool" or "visit site".

NOTES: Save only genuinely useful tips or lessons that stand on their own and are not
instructions for using a website shown in the video. Do not repeat a website's purpose,
steps, prompt, search, settings, or expected result in a note; put those in that site's
website description instead. A video that only demonstrates one or more websites can
have no notes. Give each
note a concise, specific title. Format its detail with "Key takeaway:" first, then
"Why it matters:". If the video demonstrates a procedure, add "Steps:" with numbered
actions and finish with "Expected result:". Include exact inputs or wording shown. If
there are no demonstrated steps, explain the useful concept or tip without inventing any.
Do NOT create notes for casual conversation, personal opinions without a useful lesson,
random facts with no practical or explanatory value, vague commentary, pure promotion,
or a video that does not teach a clear takeaway. When there is no solid, useful takeaway,
return notes: []. Never make up steps or claims to fill space.

Use categories only from: {CATEGORY_TEXT}. Choose "How-to & workflows" when the main
value is a sequence of actions, a search query, or a prompt-driven workflow; otherwise
choose the closest topic category.
""".strip()
LINKS_ONLY_PROMPT = f"""
Watch the entire video again and focus only on finding every website, app/site, and search
the creator uses, shows, names, or tells the viewer to open. Return ONLY this JSON:
{{"websites": [{{"url": "...", "search_query": null, "description": "...", "category": "..."}}]}}

Inspect all frames, including address bars, browser tabs, page titles, logos, QR codes,
overlays, readable text, and spoken instructions. A complete URL is NOT required. If only
the hostname/domain is visible, save that host as its HTTPS URL. If a clearly identified
service is named or shown but its URL is hidden, use the official homepage only when its
domain is unambiguous. Never invent a page path or guess an uncertain domain.

Create one separate entry per distinct destination. Each description must cover only the
website or search in that entry. Put its purpose, visible steps and exact inputs, and
expected result in that website's description; never merge instructions for different
sites into one entry.

For Google searches, include only a clearly demonstrated search (the exact query is visibly
entered/submitted or its results are actively used) or a query the creator explicitly tells
viewers to search. Capture its exact readable query and set url to the direct Google search
URL. Do not infer a query from narration or unrelated text; ignore incidental background
tabs, joke searches, and unrelated queries unless the creator deliberately uses them in the
demonstration. If the query cannot be read, do not make one up. Do not omit an identified
website just because the video does not display a complete URL. Return an empty array only
after checking the whole video and finding no identifiable websites or qualifying searches.
If a Google search is only navigation to a separately identified destination, omit the
search entry; keep it when the search itself is part of the useful workflow.

For each entry, explain the site's purpose, the input/action demonstrated, and the
expected result. Include exact prompts, search terms, model/resource names, and steps
that are visible or spoken. Use categories only from: {CATEGORY_TEXT}.
""".strip()
NOTES_PROMPT = f"""
Watch the full YouTube video, including spoken audio and readable on-screen text. Return
ONLY one JSON object:
{{"notes": [{{"title": "...", "detail": "...", "category": "..."}}]}}

Save only genuinely useful tips or lessons that stand on their own and are not instructions
for using a website shown in the video. Never duplicate a website's purpose, steps, prompt,
search, settings, or expected result as a note; those belong in that website's description.
A video containing only website demonstrations can have no notes. Use a concise, specific
title. Format each detail as "Key takeaway:" and "Why it matters:".
When the video demonstrates a procedure, add "Steps:" with numbered actions and finish
with "Expected result:". Include exact search text, prompts, model/resource names,
settings, and inputs visible or spoken in the video. For ChatGPT, explain what to paste
and what it should produce. For Hugging Face, identify the shown model, Space, or
resource and explain how to use it. If there are no demonstrated steps, explain the
useful concept or tip without inventing any. Do not save casual conversation, unsupported
personal opinions, random facts with no explanatory or practical value, vague commentary,
pure promotion, or videos with no clear takeaway. If there is no solid useful lesson,
return notes: []. Do not invent.

Allowed categories: {CATEGORY_TEXT}. Use "How-to & workflows" when the main value is a
sequence of actions, a search query, or a prompt-driven workflow; otherwise choose the
closest topic category.
""".strip()
TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "dclid", "yclid", "mc_cid", "mc_eid")


class RetryLater(Exception):
    """Raised when a model provider is temporarily unavailable or rate limited."""


def split_env_list(name, fallback_name=None):
    """Read a comma- or newline-separated environment variable."""
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


def supabase_api_key():
    """Read a backend-only Supabase secret, supporting both current and legacy names."""
    value = (os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_KEY") or "").strip()
    if not value:
        raise RuntimeError("Missing required environment variable: SUPABASE_SECRET_KEY (or SUPABASE_SERVICE_KEY)")
    return value


def supabase_auth_headers(api_key):
    headers = {"apikey": api_key, "Content-Type": "application/json"}
    # Supabase's newer opaque secret keys belong only in `apikey`; they are not JWTs.
    if not api_key.startswith("sb_"):
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def assert_local_worker_lease():
    if (os.getenv("VIDEO_WORKER_LEASE_HELD") or "").lower() != "true":
        return
    owner_id = required_env("VIDEO_WORKER_ID")
    lease_seconds = int(os.getenv("VIDEO_WORKER_LEASE_SECONDS", "180"))
    if not renew_video_lease(owner_id, lease_seconds):
        raise RuntimeError("Local worker lost its queue lease; refusing to write to Supabase")


def supabase_request(method, table, *, params=None, body=None, prefer=None):
    """Make one PostgREST request using a backend-only Supabase key."""
    base_url = required_env("SUPABASE_URL").rstrip("/")
    service_key = supabase_api_key()
    if (method.upper() in {"POST", "PATCH", "PUT", "DELETE"}
            and (os.getenv("VIDEO_WORKER_LEASE_HELD") or "").lower() == "true"):
        assert_local_worker_lease()
    headers = supabase_auth_headers(service_key)
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


def supabase_rpc(function, body):
    """Call a privileged Supabase Postgres function through PostgREST."""
    base_url = required_env("SUPABASE_URL").rstrip("/")
    service_key = supabase_api_key()
    if function in {"replace_video_links", "replace_video_notes"}:
        assert_local_worker_lease()
    response = requests.post(
        f"{base_url}/rest/v1/rpc/{function}",
        json=body,
        headers=supabase_auth_headers(service_key),
        timeout=30,
    )
    if not response.ok:
        detail = response.text[:1000].strip()
        raise RuntimeError(
            f"Supabase RPC {function} failed with HTTP {response.status_code}: "
            f"{detail or response.reason}"
        )
    if not response.content:
        return None
    return response.json()


def try_acquire_video_lease(owner_id, lease_seconds):
    return supabase_rpc("try_acquire_video_worker_lease", {
        "p_owner_id": owner_id, "p_lease_seconds": lease_seconds,
    }) is True


def renew_video_lease(owner_id, lease_seconds):
    return supabase_rpc("renew_video_worker_lease", {
        "p_owner_id": owner_id, "p_lease_seconds": lease_seconds,
    }) is True


def release_video_lease(owner_id):
    try:
        return supabase_rpc("release_video_worker_lease", {"p_owner_id": owner_id}) is True
    except Exception as exc:
        print(f"Could not release processing lease; it will expire automatically: {exc}")
        return False


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


def get_pending_shorts_for_channel(handle):
    return supabase_request(
        "GET", "videos", params={
            "select": "video_id,channel_handle,title,duration_seconds",
            "status": "eq.pending", "is_short": "eq.true",
            "channel_handle": f"eq.{handle}",
            "order": "video_id.asc", "limit": "1",
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


def get_pending_notes_for_channel(handle):
    return supabase_request(
        "GET", "videos", params={
            "select": "video_id,channel_handle,title,duration_seconds",
            "status": "neq.pending", "notes_status": "eq.pending",
            "is_short": "eq.true", "channel_handle": f"eq.{handle}",
            "order": "video_id.asc", "limit": "1",
        },
    )


def process_local_parallel_batches(batch_size, parallel_batches, videos_per_batch,
                                   analyze_video, still_owns_lease):
    """Run bounded batches concurrently, replenishing a slot when a batch completes."""
    if batch_size < 1 or parallel_batches < 1 or videos_per_batch < 1:
        raise ValueError("Batch size and local batch parallelism settings must be at least 1")
    calls = processed = links_found = notes_saved = failures = 0
    deferred = False

    def analyze_one(video, notes_only):
        video_id = video["video_id"]
        if not still_owns_lease():
            return 0, 0, 0, 0, True
        try:
            result = analyze_video(video_id, notes_only=notes_only)
            if not still_owns_lease():
                print(f"Lost local queue lease during analysis of {video_id}; discarding result.")
                return 0, 0, 0, 0, True
        except RetryLater as exc:
            print(f"OmniRoute is unavailable or rate limited; leaving {video_id} pending: {exc}")
            return 0, 0, 0, 0, True
        except Exception as exc:
            if notes_only:
                mark_notes_failed(video_id, exc)
            else:
                mark_failed(video_id, exc)
            print(f"Video {video_id} failed; it will not block other channels: {exc}")
            return 1, 0, 0, 0, 1

        if not notes_only and not result.get("websites"):
            print(f"No websites in the first pass for {video_id}; retrying with focused link extraction.")
            try:
                recovery = analyze_video(video_id, links_only=True)
                if recovery.get("websites"):
                    result["websites"] = recovery["websites"]
                else:
                    print(f"Focused extraction still found no identifiable sites for {video_id}.")
            except RetryLater as exc:
                print(f"OmniRoute became unavailable during focused extraction for {video_id}: {exc}")
                return 0, 0, 0, 0, True
            except Exception as exc:
                print(f"Focused link extraction failed for {video_id}; keeping the first result: {exc}")

        if not notes_only and not result.get("notes"):
            print(f"No useful notes in the first pass for {video_id}; retrying focused note extraction.")
            try:
                recovery = analyze_video(video_id, notes_only=True)
                if recovery.get("notes"):
                    result["notes"] = recovery["notes"]
                else:
                    print(f"Focused note extraction found no useful takeaway for {video_id}.")
            except RetryLater as exc:
                print(f"OmniRoute became unavailable during note extraction for {video_id}: {exc}")
                return 0, 0, 0, 0, True
            except Exception as exc:
                print(f"Focused note extraction failed for {video_id}; keeping the first result: {exc}")

        if notes_only:
            try:
                count = save_notes(video_id, result.get("notes", []))
                update_video(video_id, {
                    "notes_status": "done", "notes_error_message": None,
                    "notes_processed_at": datetime.now(timezone.utc).isoformat(),
                })
                print(f"Notes done {video_id}: {count} note(s)")
                return 1, 1, 0, count, False
            except Exception as exc:
                mark_notes_failed(video_id, exc)
                print(f"Saving notes for {video_id} failed: {exc}")
                return 1, 1, 0, 0, 1

        try:
            link_count = save_links(video_id, result.get("websites", []))
            update_video(video_id, {
                "status": "done", "error_message": None,
                "processed_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as exc:
            mark_failed(video_id, exc)
            print(f"Saving websites for {video_id} failed: {exc}")
            return 1, 1, 0, 0, 1

        try:
            note_count = save_notes(video_id, result.get("notes", []))
            update_video(video_id, {
                "notes_status": "done", "notes_error_message": None,
                "notes_processed_at": datetime.now(timezone.utc).isoformat(),
            })
            print(f"Done {video_id}: {link_count} website(s), {note_count} note(s)")
            return 1, 1, link_count, note_count, False
        except Exception as exc:
            mark_notes_failed(video_id, exc)
            print(f"Website scan done for {video_id}; saving notes failed: {exc}")
            return 1, 1, link_count, 0, 1

    def process_batches(notes_only):
        nonlocal calls, processed, links_found, notes_saved, failures, deferred
        active = {}
        active_ids = set()
        batch_number = 0
        with ThreadPoolExecutor(max_workers=parallel_batches) as batch_pool:
            while active or (calls < batch_size and not deferred):
                if not deferred and not still_owns_lease():
                    print("Local worker lost its queue lease; ending this pass.")
                    deferred = True

                while len(active) < parallel_batches and calls < batch_size and not deferred:
                    pending = (get_pending_notes(batch_size) if notes_only
                               else get_pending_shorts(batch_size))
                    available = [video for video in pending
                                 if video["video_id"] not in active_ids]
                    if not available:
                        break
                    batch = available[:min(videos_per_batch, batch_size - calls)]
                    calls += len(batch)
                    batch_number += 1
                    video_ids = {video["video_id"] for video in batch}
                    active_ids.update(video_ids)
                    print(f"Starting local batch {batch_number} with {len(batch)} video(s)")

                    def run_batch(videos):
                        with ThreadPoolExecutor(max_workers=videos_per_batch) as video_pool:
                            futures = [video_pool.submit(analyze_one, video, notes_only)
                                       for video in videos]
                            return [future.result() for future in as_completed(futures)]

                    active[batch_pool.submit(run_batch, batch)] = video_ids

                if not active:
                    break

                completed, _ = wait(active, return_when=FIRST_COMPLETED)
                for future in completed:
                    video_ids = active.pop(future)
                    active_ids.difference_update(video_ids)
                    print(f"Local batch completed ({len(video_ids)} video(s))")
                    for call_count, done_count, link_count, note_count, failed in future.result():
                        processed += done_count
                        links_found += link_count
                        notes_saved += note_count
                        failures += failed
                        if call_count == 0:
                            deferred = True

    process_batches(notes_only=False)
    if calls < batch_size and not deferred:
        process_batches(notes_only=True)
    return calls, processed, links_found, notes_saved, failures


def process_local_parallel_batch(batch_size, parallelism, analyze_video, still_owns_lease):
    """Compatibility wrapper for legacy single-wave local settings."""
    return process_local_parallel_batches(
        batch_size, parallel_batches=1, videos_per_batch=parallelism,
        analyze_video=analyze_video, still_owns_lease=still_owns_lease,
    )


def parse_model_json(text):
    if not isinstance(text, str):
        raise ValueError("Model response text is missing")
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            data, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        if not isinstance(data.get("websites", []), list):
            continue
        if not isinstance(data.get("notes", []), list):
            continue
        # Accept JSON wrapped in markdown or explanatory text, and ignore trailing
        # commentary/duplicate output after the first valid response object.
        return data
    raise ValueError("Model response did not contain a valid websites/notes JSON object")


def gemini_call(clients, models, video_id, *, notes_only=False, links_only=False):
    """Analyze a YouTube video with GitHub's Gemini fallback configuration."""
    from google.genai import types

    video_url = f"https://www.youtube.com/watch?v={video_id}"
    prompt = NOTES_PROMPT if notes_only else LINKS_ONLY_PROMPT if links_only else PROMPT
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
                response_text = getattr(response, "text", None)
                if not response_text:
                    raise ValueError("Gemini returned an empty response")
                return parse_model_json(response_text)
            except Exception as exc:
                status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
                message = str(exc)
                rate_limited = (str(status) == "429" or "429" in message
                                or "RESOURCE_EXHAUSTED" in message.upper()
                                or "rate limit" in message.lower())
                errors.append((model, client_index, rate_limited, message[:500]))
                print(f"Gemini model {model} with key slot {client_index} failed: {message[:300]}")

    if errors and all(item[2] for item in errors):
        raise RetryLater("All configured Gemini models/keys are rate limited")
    summary = "; ".join(
        f"{model} (key slot {key_index}): {message}"
        for model, key_index, _, message in errors
    )
    raise RuntimeError(f"All configured Gemini fallbacks failed: {summary}")


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
    host = parts.hostname.encode("idna").decode("ascii").lower().removeprefix("www.")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if parts.port and not ((parts.scheme.lower() == "http" and parts.port == 80)
                           or (parts.scheme.lower() == "https" and parts.port == 443)):
        host = f"{host}:{parts.port}"
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith(TRACKING_PREFIXES):
            continue
        query.append((key, value))
    query.sort()
    scheme = parts.scheme.lower()
    if scheme == "http":
        scheme = "https"
    path = parts.path.rstrip("/")
    cleaned = urlunsplit((scheme, host, path,
                          urlencode(query, doseq=True), ""))
    return cleaned, parts.hostname.lower().removeprefix("www.")


def omniroute_response_text(response):
    """Extract assistant text from an OpenAI-compatible OmniRoute response."""
    try:
        choice = response["choices"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("OmniRoute returned no assistant message") from exc
    message = choice.get("message") or {}
    content = message.get("content")
    if content is None:
        content = message.get("output_text") or choice.get("text")
    if isinstance(content, str):
        return content

    def text_from_part(part):
        if isinstance(part, str):
            return part
        if isinstance(part, dict):
            for key in ("text", "output_text", "content"):
                value = part.get(key)
                if isinstance(value, str):
                    return value
                if isinstance(value, list):
                    nested = "".join(text_from_part(item) for item in value)
                    if nested:
                        return nested
        return ""

    if isinstance(content, (list, dict)):
        extracted = text_from_part(content)
        if extracted:
            return extracted
    if isinstance(content, list):
        shape = ",".join(str(part.get("type", "?")) for part in content if isinstance(part, dict))
    elif isinstance(content, dict):
        shape = ",".join(content.keys())
    else:
        shape = type(content).__name__
    raise ValueError(f"OmniRoute assistant content has unsupported shape: {shape or 'empty'}")


def omniroute_call(api_key, base_url, models, video_id, *, notes_only=False, links_only=False):
    """Analyze a YouTube video via OmniRoute's OpenAI-compatible chat endpoint."""
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    prompt = NOTES_PROMPT if notes_only else LINKS_ONLY_PROMPT if links_only else PROMPT
    endpoint = f"{base_url.rstrip('/')}/chat/completions"
    errors = []
    for model in models:
        try:
            response = requests.post(
                endpoint,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "video_url", "video_url": {"url": video_url}},
                        ],
                    }],
                    "temperature": 0,
                    "stream": False,
                },
                timeout=(8, 180),
            )
            if not response.ok:
                detail = response.text[:500].strip()
                raise requests.HTTPError(
                    f"HTTP {response.status_code}: {detail or response.reason}",
                    response=response,
                )
            response_body = response.json()
            bridge_info = response.headers.get("x-omniroute-modality-bridge")
            if bridge_info:
                print(f"OmniRoute video bridge used for {video_id}: {bridge_info[:240]}")
            else:
                print(
                    f"OmniRoute did not report modality-bridge processing for {video_id}; "
                    "check whether this model/provider accepts video_url natively."
                )
            response_text = omniroute_response_text(response_body)
            try:
                return parse_model_json(response_text)
            except ValueError as exc:
                # This distinguishes a model refusing/being unable to inspect the video
                # from malformed JSON without dumping a full response into worker logs.
                preview = " ".join(response_text.split())[:240]
                finish_reason = "unknown"
                try:
                    finish_reason = str(response_body["choices"][0].get("finish_reason") or "unknown")
                except (KeyError, IndexError, TypeError):
                    pass
                raise ValueError(
                    f"{exc}; finish_reason={finish_reason}; response_preview={preview!r}"
                ) from exc
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            message = str(exc)
            retryable = (
                isinstance(exc, (requests.ConnectionError, requests.Timeout))
                or status in {408, 425, 429, "408", "425", "429"}
                or (isinstance(status, int) and status >= 500)
                or "rate limit" in message.lower()
                or "quota" in message.lower()
            )
            errors.append((model, retryable, message[:500]))
            print(f"OmniRoute model {model} failed: {message[:300]}")

    if errors and all(item[1] for item in errors):
        summary = "; ".join(f"{model}: {message}" for model, _, message in errors)
        raise RetryLater(f"OmniRoute is unavailable or rate limited: {summary}")
    summary = "; ".join(f"{model}: {message}" for model, _, message in errors)
    raise RuntimeError(f"All configured OmniRoute fallbacks failed: {summary}")


def is_google_host(host):
    host = (host or "").lower().removeprefix("www.")
    return re.fullmatch(r"google\.[a-z]{2,3}(?:\.[a-z]{2})?", host) is not None


GOOGLE_QUERY_STOP_WORDS = {
    "a", "an", "and", "app", "best", "com", "find", "for", "free",
    "google", "how", "in", "official", "of", "on", "search", "site",
    "the", "to", "tool", "use", "website", "with",
}


def google_search_terms(url):
    parts = urlsplit(url)
    if (not is_google_host(parts.hostname)
            or parts.path.rstrip("/").lower() != "/search"):
        return set()
    query = dict(parse_qsl(parts.query, keep_blank_values=True)).get("q", "")
    terms = {
        word for word in re.findall(r"[a-z0-9]+", query.lower())
        if len(word) >= 3 and word not in GOOGLE_QUERY_STOP_WORDS
    }
    # A single specific brand name (for example, "chatgpt") can identify a
    # destination. Very short one-word queries are too ambiguous to remove.
    if len(terms) == 1 and len(next(iter(terms))) < 6:
        return set()
    return terms


def destination_site_terms(row):
    parts = urlsplit(row["url"])
    text = " ".join((row.get("domain", ""), parts.hostname or "", parts.path))
    return {
        word for word in re.findall(r"[a-z0-9]+", text.lower())
        if len(word) >= 3 and word not in {"www", "com", "org", "net", "app", "html", "htm"}
    }


def save_links(video_id, results):
    rows_by_url = {}
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("Each JSON array item must be an object")
        raw_url = result.get("url", "")
        search_query = result.get("search_query")
        url, domain = normalize_url(raw_url)
        if isinstance(search_query, str) and search_query.strip() and is_google_host(domain):
            raw_url = "https://www.google.com/search?" + urlencode({"q": search_query.strip()})
            url, domain = normalize_url(raw_url)
        category = result.get("category", "Other")
        if not isinstance(category, str) or category not in CATEGORIES:
            category = "Other"
        description = result.get("description", "")
        if not isinstance(description, str):
            description = str(description)
        candidate = {
            "url": url, "domain": domain,
            "description": description.strip(), "category": category,
        }
        existing = rows_by_url.get(url)
        if existing is None or len(candidate["description"]) > len(existing["description"]):
            rows_by_url[url] = candidate
    # Remove a Google search only when its meaningful query words all identify
    # another URL's host/path from this same video. Distinct search workflows
    # and unrelated website URLs are retained.
    destination_rows = [row for row in rows_by_url.values()
                        if not is_google_host(row["domain"])]
    redundant_search_urls = set()
    for url, row in rows_by_url.items():
        terms = google_search_terms(url)
        if terms and any(terms.issubset(destination_site_terms(destination))
                         for destination in destination_rows):
            redundant_search_urls.add(url)
    for url in redundant_search_urls:
        del rows_by_url[url]
    rows = list(rows_by_url.values())
    if not rows:
        print(f"No website URLs were extracted for {video_id}; keeping any existing links.")
        return 0
    supabase_rpc("replace_video_links", {"p_video_id": video_id, "p_rows": rows})
    return len(rows)


def save_notes(video_id, results):
    """Save short takeaways, ignoring duplicate titles from the same video."""
    rows_by_title = {}
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
        rows_by_title[title.strip()] = {
            "title": title.strip(), "detail": detail.strip(), "category": category,
        }
    rows = list(rows_by_title.values())
    supabase_rpc("replace_video_notes", {"p_video_id": video_id, "p_rows": rows})
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
    # Check Supabase credentials before starting work.
    required_env("SUPABASE_URL")
    supabase_api_key()

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

    lease_owner = (os.getenv("VIDEO_WORKER_ID") or
                   f"{socket.gethostname()}-{uuid.uuid4().hex[:12]}")
    external_lease = (os.getenv("VIDEO_WORKER_LEASE_HELD") or "").lower() == "true"
    lease_seconds = int(os.getenv(
        "VIDEO_WORKER_LEASE_SECONDS", "180" if external_lease else "4200"
    ))
    if external_lease:
        if not renew_video_lease(lease_owner, lease_seconds):
            print("Local worker no longer owns the processing lease; skipping this pass.")
            return
    else:
        if not try_acquire_video_lease(lease_owner, lease_seconds):
            print("Another worker owns the processing lease; skipping this pass.")
            return
        atexit.register(release_video_lease, lease_owner)

    provider = (os.getenv("AI_PROVIDER") or "omniroute").strip().lower()
    if provider == "omniroute":
        omniroute_api_key = required_env("OMNIROUTE_API_KEY")
        omniroute_base_url = required_env("OMNIROUTE_BASE_URL")
        models = split_env_list("OMNIROUTE_MODELS", "OMNIROUTE_MODEL")
        if not models:
            raise RuntimeError("Missing required environment variable: OMNIROUTE_MODELS (or OMNIROUTE_MODEL)")

        def analyze_video(video_id, *, notes_only=False, links_only=False):
            return omniroute_call(
                omniroute_api_key, omniroute_base_url, models,
                video_id, notes_only=notes_only, links_only=links_only,
            )
    elif provider == "gemini":
        from google import genai

        gemini_keys = split_env_list("GEMINI_API_KEYS", "GEMINI_API_KEY")
        if not gemini_keys:
            raise RuntimeError("Missing required environment variable: GEMINI_API_KEYS (or GEMINI_API_KEY)")
        models = split_env_list("GEMINI_MODELS", "GEMINI_MODEL")
        if not models:
            raise RuntimeError("Missing required environment variable: GEMINI_MODELS (or GEMINI_MODEL)")
        clients = [genai.Client(api_key=key) for key in gemini_keys]

        def analyze_video(video_id, *, notes_only=False, links_only=False):
            return gemini_call(
                clients, models, video_id, notes_only=notes_only, links_only=links_only,
            )
    else:
        raise ValueError("AI_PROVIDER must be 'omniroute' or 'gemini'")
    print(f"AI provider: {provider}; model(s): {', '.join(models)}")

    batch_size = int(os.getenv("BATCH_SIZE", "5"))
    if batch_size < 1:
        raise ValueError("BATCH_SIZE must be at least 1")

    def still_owns_external_lease():
        if not external_lease:
            return True
        return renew_video_lease(lease_owner, lease_seconds)

    local_parallel_batches = int(os.getenv("LOCAL_PARALLEL_BATCHES", "0"))
    local_videos_per_batch = int(os.getenv("LOCAL_VIDEOS_PER_BATCH", "2"))
    local_parallelism = int(os.getenv("LOCAL_PARALLEL_CHANNELS", "0"))
    if local_parallel_batches < 0:
        raise ValueError("LOCAL_PARALLEL_BATCHES cannot be negative")
    if local_videos_per_batch < 1:
        raise ValueError("LOCAL_VIDEOS_PER_BATCH must be at least 1")
    if local_parallelism < 0:
        raise ValueError("LOCAL_PARALLEL_CHANNELS cannot be negative")
    if local_parallel_batches and external_lease and provider == "omniroute":
        calls, processed, links_found, notes_saved, failures = process_local_parallel_batches(
            batch_size, local_parallel_batches, local_videos_per_batch,
            analyze_video, still_owns_external_lease,
        )
        print("\nRun summary")
        print(f"Upload video rows checked: {discovered_count}")
        print(f"Videos started in this pass: {calls}; completed: {processed}")
        print(f"Website links found and saved: {links_found}")
        print(f"Notes found and saved: {notes_saved}")
        print(f"Processing failures: {failures}")
        print(f"Channel scan failures: {channel_errors}")
        if failures or channel_errors:
            sys.exit(1)
        return
    if local_parallelism and external_lease and provider == "omniroute":
        calls, processed, links_found, notes_saved, failures = process_local_parallel_batch(
            batch_size, local_parallelism, analyze_video, still_owns_external_lease,
        )
        print("\nRun summary")
        print(f"Upload video rows checked: {discovered_count}")
        print(f"Videos started in this pass: {calls}; completed: {processed}")
        print(f"Website links found and saved: {links_found}")
        print(f"Notes found and saved: {notes_saved}")
        print(f"Processing failures: {failures}")
        print(f"Channel scan failures: {channel_errors}")
        if failures or channel_errors:
            sys.exit(1)
        return

    pending = get_pending_shorts(batch_size)
    calls = processed = links_found = notes_saved = failures = 0
    deferred = False

    def prepare_model_call():
        nonlocal calls
        if calls:
            time.sleep(4)
        calls += 1

    # New pending Shorts get one model call that extracts links and notes together.
    for video in pending:
        video_id = video["video_id"]
        if not still_owns_external_lease():
            print("Local worker lost its queue lease; ending this pass.")
            return
        prepare_model_call()
        try:
            result = analyze_video(video_id)
            if not still_owns_external_lease():
                print("Local worker lost its queue lease during the model request; discarding the result.")
                return
        except RetryLater as exc:
            print(f"{provider} is unavailable or rate limited; leaving this video pending: {exc}")
            deferred = True
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
            note_items = result.get("notes", [])
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
    if remaining > 0 and not deferred:
        old_notes = get_pending_notes(remaining)
        for video in old_notes:
            video_id = video["video_id"]
            if not still_owns_external_lease():
                print("Local worker lost its queue lease; ending this pass.")
                return
            prepare_model_call()
            try:
                result = analyze_video(video_id, notes_only=True)
                if not still_owns_external_lease():
                    print("Local worker lost its queue lease during the model request; discarding the result.")
                    return
            except RetryLater as exc:
                print(f"{provider} is unavailable or rate limited; leaving notes pending: {exc}")
                deferred = True
                break
            except Exception as exc:
                failures += 1
                mark_notes_failed(video_id, exc)
                print(f"Notes for {video_id} failed; continuing: {exc}")
                continue
            processed += 1

            try:
                note_items = result.get("notes", [])
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
    print(f"Video model calls completed: {processed}")
    print(f"Website links found and saved: {links_found}")
    print(f"Notes found and saved: {notes_saved}")
    print(f"Processing failures: {failures}")
    print(f"Channel scan failures: {channel_errors}")
    # Report a failed pass after the rest of the available batch is attempted.
    if failures or channel_errors:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Run could not start: {exc}", file=sys.stderr)
        sys.exit(1)
