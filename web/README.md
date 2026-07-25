# SubFit (Vercel edition)

This is a Vercel-deployable rewrite of SubFit — see the [repo root README](../README.md)
for what SubFit does. Everything here runs as a single Next.js app:

- **Frontend**: React (App Router), same three tabs as the local Python version
  (Subreddit Setup, Draft Checker, Saved Drafts).
- **Backend**: Next.js Route Handlers under `src/app/api/*` (serverless
  functions on Vercel).
- **Database**: Postgres (Vercel Postgres / Neon, or any Postgres) instead of
  SQLite, since serverless functions don't have persistent local disk.
- **Reddit access**: plain `fetch()`, with two modes chosen automatically:
  - **Authenticated** (recommended): if `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET`
    are set, uses OAuth2 `client_credentials` (the same read-only "script app"
    flow PRAW uses) — no PRAW/Python involved. Higher rate limits.
  - **Anonymous fallback**: if no credentials are set, falls back to Reddit's
    public, unauthenticated `.json` endpoints. **No Reddit app/registration
    needed at all** — useful if you just want to try SubFit out, or if
    Reddit's app-creation form (which requires solving a reCAPTCHA) is giving
    you trouble. Lower rate limits, but enough for personal use and testing.
- **Embeddings**: [transformers.js](https://huggingface.co/docs/transformers.js)
  running `Xenova/all-MiniLM-L6-v2` in Node (no Python/torch, no external LLM
  API calls) — the same model family the local app uses. This is best-effort:
  if it can't load (offline, or too heavy for your deploy target), the app
  automatically falls back to rule/vocabulary-only scoring, same as the local
  app's behavior when its embedding model can't load.

Why this looks different from the local Python app: Vercel serverless
functions are stateless (no persistent SQLite file) and time-limited (a full
3,000–5,000-post corpus fetch would exceed most execution limits). To fit
that model, corpus fetching here is **chunked**: the UI kicks off a fetch job
and polls a `step` endpoint repeatedly (with a progress bar) until the corpus
is fully cached, instead of blocking on one long request.

## 1. (Optional) Create a Reddit API app

This step is optional — skip it and SubFit will use Reddit's public API
anonymously (lower rate limits, but works fine for personal use). Come back
to this later if you want higher limits.

Same as the local app — see the [repo root README](../README.md#1-create-a-reddit-api-app)
for the step-by-step. You'll end up with a **client ID** and **client secret**.
If Reddit's app-creation form's reCAPTCHA won't cooperate (a known pain
point — try a different browser or check that third-party cookies aren't
blocked if so), don't let it block you from trying SubFit out; just move on
without it.

## 2. Provision a Postgres database

Pick one:

- **Vercel Postgres (Neon-backed)**: in your Vercel project, go to
  **Storage → Create Database → Postgres**. Vercel will set a `POSTGRES_URL`
  env var on the project automatically. Copy that same value into a
  `DATABASE_URL` env var too (this app reads `DATABASE_URL`, falling back to
  `POSTGRES_URL`), or just add `DATABASE_URL` pointing at the same connection
  string.
- **Neon / Supabase / any hosted Postgres**: create a database, copy its
  connection string into `DATABASE_URL`.
- **Local Postgres** (for development only): point `DATABASE_URL` at
  `postgres://user:pass@localhost:5432/subfit`.

The app creates its own tables on first request — no manual migration step.

## 3. Configure environment variables

Locally:

```bash
cd web
cp .env.example .env.local
```

Edit `.env.local`:

```
DATABASE_URL=postgres://...

# Optional -- omit all three and SubFit uses Reddit's public API anonymously
REDDIT_CLIENT_ID=the_personal_use_script_string
REDDIT_CLIENT_SECRET=the_secret_string
REDDIT_USER_AGENT=subfit:draft-checker:v1.0 (by u/your_reddit_username)
```

On Vercel: **Project Settings → Environment Variables** — add `DATABASE_URL`
(should already exist if you used Vercel Postgres above) and, optionally, the
three Reddit variables.

## 4. Run locally

```bash
cd web
npm install
npm run dev
```

Open `http://localhost:3000`.

Run the test suite (parsing/TF-IDF/scoring logic, ported 1:1 from the local
Python app and cross-checked against it):

```bash
npm test
```

## 5. Deploy to Vercel

Either:

- **Dashboard**: import the GitHub repo at <https://vercel.com/new>, set the
  **root directory** to `web/` (since this is a subdirectory of the repo),
  add the env vars from step 3, and deploy.
- **CLI**:
  ```bash
  cd web
  npm install -g vercel   # if you don't have it
  vercel link
  vercel env add DATABASE_URL
  vercel env add REDDIT_CLIENT_ID
  vercel env add REDDIT_CLIENT_SECRET
  vercel env add REDDIT_USER_AGENT
  vercel deploy --prod
  ```

## Notes & limitations specific to this deployment

- **Corpus fetching is chunked and can take a while for large subreddits.**
  The UI polls automatically and shows a progress bar; don't navigate away
  mid-fetch or you'll need to click "Fetch / Refresh" again (the job resumes
  from the database, but there's no background worker to finish it for you
  while the tab is closed).
- **Vercel's Hobby plan caps function execution at ~10-60s**; each fetch
  "step" only pulls a few Reddit listing pages at a time specifically to stay
  well under that, regardless of plan. If you're on Pro/Enterprise with
  higher `maxDuration` limits, it'll still work the same way — just as
  reliably, with no code changes needed.
- **Embeddings are optional and best-effort.** transformers.js downloads its
  model from the Hugging Face Hub on first use per warm function instance. If
  your deployment can't reach it (or the function environment can't load it
  in time), semantic similarity is simply omitted from results — explicit
  rule/AutoModerator hits and vocabulary-outlier detection are unaffected.
- **Read-only.** Same as the local app: this only ever calls Reddit's
  read-only endpoints. It cannot post, comment, vote, or message.
