# Use OmniRoute for video processing

The scheduled GitHub Actions worker can send model requests to OmniRoute. The
worker itself remains on GitHub; OmniRoute must be reachable from GitHub Actions
(a `localhost` URL on your PC will not work).

## Configure GitHub

In the repository's **Settings → Secrets and variables → Actions**, add:

**Repository variables**

- `AI_PROVIDER` = `omniroute`
- `OMNIROUTE_BASE_URL` = your OmniRoute API root, including `/v1` (for example,
  `https://your-host.example/v1`)
- `OMNIROUTE_MODELS` = the model ID shown by OmniRoute's `GET /v1/models`;
  comma-separated IDs can be supplied as fallbacks

**Repository secret**

- `OMNIROUTE_API_KEY` = an API key created in your OmniRoute instance

Keep the API key in GitHub Secrets, never in a repository variable or source
file. `AI_PROVIDER` defaults to `gemini`, so the existing Gemini configuration
continues to work unless you explicitly switch it to `omniroute`.

## Video input

The worker sends each YouTube URL as an OpenAI-compatible `video_url` content
part to `/chat/completions`. OmniRoute's Video Bridge can turn a URL into sampled
frames for a model without native video support, but the bridge must be available
and enabled in your OmniRoute instance. Confirm that your selected model can
accept video input (directly or through the bridge) before switching scheduled
processing over.

After configuring the variables and secret, use **Actions → Process pending
videos → Run workflow** with a batch size of `1` for the first run. Review the
run log and the saved result before relying on the scheduled workflow.

## Antigravity account note

OmniRoute's Antigravity onboarding uses Google-account OAuth. There are recent
user reports of account suspensions associated with routing Antigravity through
OmniRoute. These are reports rather than an official Google determination, but
consider that risk before connecting an account you rely on.
