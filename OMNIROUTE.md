# Local OmniRoute with GitHub Gemini fallback

When your PC worker is running, it discovers recent uploads from `channels.txt`
and processes the shared Supabase queue using OmniRoute only. The local worker
checks up to 50 recent uploads per channel hourly by default; change
`LOCAL_DISCOVERY_INTERVAL_SECONDS` or `DISCOVERY_LIMIT` in `.env.local` if you
want a different cadence or scan size. With `LOCAL_PARALLEL_BATCHES=2` and
`LOCAL_VIDEOS_PER_BATCH=2`, it runs two batches at once, with two videos in each
batch (four active videos total). When a batch finishes, it starts the next one
automatically. `BATCH_SIZE` limits videos per pass; setting it to 1000 lets the
worker keep launching batches until the pending queue is empty or 1000 videos have
started. The local scheduler selects across all configured channels.
When a local first pass returns no websites or notes, the worker makes a focused
second pass for the missing content before saving an empty result.
`BATCH_SIZE` is the maximum number of videos started in a pass. The local-only
`LOCAL_PARALLEL_BATCHES=2` and `LOCAL_VIDEOS_PER_BATCH=2` settings allow four videos
to be active across two independently replenished batches. Focused link and note retries
can add requests when content is empty. GitHub's Gemini processor remains
sequential and does not use the local parallel setting. The daily GitHub discovery
workflow also checks channels. GitHub's separate processor uses Gemini every 15 minutes when
it can acquire the queue lease, so pending items can be processed while your PC
is off. The local worker never switches to Gemini.

## One-time Supabase setup

Run these SQL files in the Supabase SQL Editor for the project used by the app.
If Notes has not been enabled in this Supabase project yet, run
[`supabase/notes.sql`](supabase/notes.sql) first. Push the updated code with both
the local OmniRoute worker and GitHub Gemini processor before applying the
content refresh migration:

1. [`supabase/worker_lease.sql`](supabase/worker_lease.sql) creates the shared
   worker lease so two local workers cannot process the queue at once.
2. [`supabase/content_quality.sql`](supabase/content_quality.sql) adds the
   "How-to & workflows" category and installs the content-replacement functions.
3. [`supabase/site_collaboration.sql`](supabase/site_collaboration.sql) enables
   saved comments and owner-only edits. It requires the existing `links`, `notes`,
   and `videos` tables, preserves edited/commented rows during model refreshes,
   and installs editor-only update permissions. Whichever worker owns the lease
   processes the queue: OmniRoute locally or Gemini on GitHub when the local worker is off.
4. [`supabase/global_website_dedup.sql`](supabase/global_website_dedup.sql) merges
   existing exact-URL duplicates and makes each exact URL a single website entry.
   It records every source video separately so each source's notes remain visible
   from the website card. Run this migration after the preceding files.
5. [`supabase/normalize_website_urls.sql`](supabase/normalize_website_urls.sql) merges
   older `http`, `www`, and trailing-slash variants. Run it after the global dedup
   migration, then requeue the affected Shorts if their descriptions need refreshing.

Existing links and notes remain visible until each video's new result is saved.

## Set up the local worker

1. Start OmniRoute and connect the model you want to use. For routes that do not
   accept video natively, open **Settings → Modality Bridge → Video**, enable
   the Video Bridge, choose an available vision model, and confirm the runtime
   reports FFmpeg/ffprobe as available. The Video Bridge is opt-in in OmniRoute;
   without native video support or the bridge, a `video_url` part may not reach
   the model as video. Successful bridged responses include the
   `x-omniroute-modality-bridge` response header; the local worker now logs this
   header (or reports when OmniRoute did not return it).
2. Copy `.env.local.example` to `.env.local` in the project folder. Fill in
   `SUPABASE_URL`, a backend-only Supabase key, `YOUTUBE_API_KEY`,
   `OMNIROUTE_API_KEY`, and a model ID listed by OmniRoute's `/v1/models`
   endpoint.
3. Install the packages and start the worker:

   ```powershell
   py -m pip install -r requirements.txt
   py scripts/local_worker.py
   ```

   The local requirements exclude the Gemini SDK; only the GitHub processor
   installs it.

4. To keep the worker running after sign-in, create a Windows Task Scheduler
   task that starts `py` with argument `scripts/local_worker.py` and the project
   folder as its working directory. Start OmniRoute before the worker.

Stop a manually started worker with Ctrl+C. If the PC is shut down unexpectedly,
the queue lease expires after three minutes. Pending videos resume when the
worker starts again.

## Content quality changes

Each website description now explains the video's purpose for that site, the
specific text or action to enter, and the expected result. Visible Google
clearly demonstrated or explicitly requested Google queries become direct search links,
labeled by their query; queries inferred from narration and incidental background tabs are
ignored, and a bare Google homepage is not saved just because it appeared in the video. ChatGPT prompts
and Hugging Face models/Spaces are described with the demonstrated inputs and
steps. Notes are saved only for clear, informative tips or lessons that stand on
their own and are not instructions for the websites shown. Casual conversation,
unsupported opinions, random facts with no explanatory or practical value, vague
commentary, and pure promotion should produce no notes. Website-specific steps,
prompts, searches, settings, and expected results belong in that website's description.
A video showing multiple destinations gets a separate entry and description for each.
The new "How-to & workflows" category groups step-based instructions, searches, and
prompt-driven tasks.

## GitHub secrets

Keep your Gemini credentials in GitHub repository **Settings → Secrets and
variables → Actions** for the scheduled fallback processor. It reads
`GEMINI_API_KEY` or `GEMINI_API_KEYS`, plus a model from the `GEMINI_MODELS`
repository variable or `GEMINI_MODEL` secret. Both GitHub workflows need
`YOUTUBE_API_KEY`, `SUPABASE_URL`, and either `SUPABASE_SECRET_KEY` or the
legacy `SUPABASE_SERVICE_KEY`. Do not put Gemini credentials in `.env.local`;
the local worker explicitly selects OmniRoute.

Keep local OmniRoute and Supabase keys in `.env.local` or a private secret
store; `.env.local` is ignored by Git. Supabase secret/service-role keys have
elevated database access.

## Enable your editor account

1. In Supabase **Authentication → Users**, create your email/password account.
   Leave public sign-up disabled if you do not want visitors creating accounts.
2. In the SQL Editor, run this allowlist statement with the account email you
   created, or use [`supabase/add_site_editor.sql`](supabase/add_site_editor.sql)
   after replacing its example address:

   ```sql
   insert into public.site_editors (user_id)
   select id from auth.users where email = 'you@example.com'
   on conflict (user_id) do nothing;
   ```
3. Sign in on the Websites or Notes page. Only allowlisted accounts see the
   Edit controls. Anyone can post comments; comments and site content have no
   delete controls.

To refresh videos that contain YouTube, ChatGPT, Hugging Face, or Google links,
review and run `supabase/requeue_selected_site_videos.sql`. It requeues the full
videos, so the worker refreshes all links and notes attached to those videos,
not only the matching site entries.

To reprocess every Short that already has a website/search or note, review and run
[`supabase/requeue_all_existing_content.sql`](supabase/requeue_all_existing_content.sql).
Deploy the updated worker first. The script resets queue status for the matching Shorts;
the worker then refreshes their website descriptions and notes. Replacement functions
preserve manually edited or commented content.
