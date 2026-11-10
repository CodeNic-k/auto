# Local OmniRoute with GitHub Gemini fallback

When your PC worker is running, it discovers recent uploads from `channels.txt`
and processes the shared Supabase queue using OmniRoute only. The local worker
checks up to 50 recent uploads per channel hourly by default; change
`LOCAL_DISCOVERY_INTERVAL_SECONDS` or `DISCOVERY_LIMIT` in `.env.local` if you
want a different cadence or scan size. The daily GitHub discovery workflow also
checks channels. GitHub's separate processor uses Gemini every 15 minutes when
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
   "How-to & workflows" category, installs safe content-replacement functions,
   and requeues existing Shorts for refreshed descriptions and notes. Whichever
   worker owns the lease will process the queue: OmniRoute locally or Gemini on
   GitHub when the local worker is unavailable.

The second migration reprocesses all rows marked as Shorts. Their old links and
notes remain visible until each video's new result is saved; then the new rows
replace the old ones atomically. The local worker uses OmniRoute while it holds
the lease. When that worker is off, GitHub uses Gemini to drain the same queue.

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
