# Local OmniRoute with GitHub Gemini fallback

When your PC worker is running, it discovers recent uploads from `channels.txt`
and processes the shared Supabase queue using OmniRoute only. The local worker
checks up to 50 recent uploads per channel hourly by default; change
`LOCAL_DISCOVERY_INTERVAL_SECONDS` or `DISCOVERY_LIMIT` in `.env.local` if you
want a different cadence or scan size. It processes up to four videos at once,
choosing one pending video from each of four configured channels per wave.
When a local first pass returns no websites, the worker makes one extra focused
link-extraction request before saving an empty result.
`BATCH_SIZE` is the total number of videos in a pass; a focused retry can add
one extra request for a video with no extracted sites. `LOCAL_PARALLEL_CHANNELS`
sets the number of simultaneous channel slots. GitHub's Gemini processor remains
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

Existing links and notes remain visible until each video's new result is saved.

## Set up the local worker

1. Start OmniRoute and connect the model you want to use. Confirm that it can
   analyze video input directly or through OmniRoute's Video Bridge.
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
queries become direct search links, labeled by their query; a bare Google
homepage is not saved just because it appeared in the video. ChatGPT prompts
and Hugging Face models/Spaces are described with the demonstrated inputs and
steps. Notes are saved only for clear, informative lessons, useful tips, or
reproducible workflows. Casual conversation, unsupported opinions, random facts
with no explanatory or practical value, vague commentary, and pure promotion
should produce no notes. Saved notes start with the main takeaway and give
specific steps and expected results. The new "How-to & workflows" category
groups step-based instructions, searches, and prompt-driven tasks.

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
