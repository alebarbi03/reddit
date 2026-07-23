# SubFit

Checks whether a draft Reddit post/comment fits a specific subreddit's norms
and rules **before you post it** — without needing historical
removal/ban data (Reddit doesn't expose that).

SubFit works by:

1. Pulling a large sample of **currently live** posts from a target
   subreddit via the official Reddit API (PRAW) and building a "normal
   vocabulary fingerprint" of that subreddit (TF-IDF word/phrase frequency
   + sentence-transformer topic embeddings).
2. Separately pulling the subreddit's public rules and, if publicly
   readable, its AutoModerator wiki config
   (`/r/{sub}/wiki/config/automoderator` or `/r/{sub}/wiki/automoderator`)
   for explicit banned keywords/patterns.
3. Comparing your draft against both, and showing a risk score +
   highlighted draft explaining why each flagged part is risky.

## Two ways to run SubFit

| | This directory (below) | [`web/`](web/README.md) |
|---|---|---|
| Stack | Python: FastAPI + Streamlit + SQLite | Next.js (React + API routes) + Postgres |
| Hosting | Your own machine only | Vercel (or any Node host) |
| Corpus fetch | One blocking request | Chunked, polled with a progress bar (serverless-timeout-safe) |
| Embeddings | sentence-transformers (Python) | transformers.js (Node, no Python) |

Both implement the same core logic (TF-IDF vocabulary fingerprinting,
AutoModerator parsing, risk scoring) and degrade the same way if the
embedding model can't load — pick whichever fits how you want to run this.
The rest of this README covers the local Python version; see
[`web/README.md`](web/README.md) for the Vercel-hosted version.

---

Everything below runs locally. SubFit is **read-only** — it never posts, comments,
votes, or otherwise writes to Reddit.

## Architecture

```
backend/    FastAPI app (Python) — Reddit fetching, TF-IDF + embedding
            fingerprinting, scoring, SQLite cache
frontend/   Streamlit app — subreddit setup, draft checker, saved drafts
data/       SQLite database (created automatically, gitignored)
```

## 1. Create a Reddit API app

1. Log in to Reddit and go to <https://www.reddit.com/prefs/apps>.
2. Click **"create another app..."** (bottom of the page).
3. Fill in:
   - **name**: anything, e.g. `subfit`
   - **type**: select **script**
   - **description**: optional
   - **about url**: leave blank
   - **redirect uri**: `http://localhost:8080` (required by the form, unused
     by a script app)
4. Click **create app**.
5. You'll see a box with your app's name. Note down:
   - the string under "personal use script" (just under the app name) —
     this is your **client_id**
   - the value next to **secret** — this is your **client_secret**

Read-only script apps do not require your Reddit password anywhere in
SubFit; PRAW authenticates as your app in read-only mode.

## 2. Configure `.env`

From the project root:

```bash
cp .env.example .env
```

Edit `.env`:

```
REDDIT_CLIENT_ID=the_personal_use_script_string
REDDIT_CLIENT_SECRET=the_secret_string
REDDIT_USER_AGENT=subfit:draft-checker:v1.0 (by u/your_reddit_username)
```

Reddit requires a descriptive, unique user agent — including your Reddit
username in it (as shown) is recommended and helps avoid rate-limit issues.

The other variables in `.env.example` (`SUBFIT_DB_PATH`,
`SUBFIT_DEFAULT_POST_LIMIT`, `SUBFIT_MAX_POST_LIMIT`) are optional and have
sensible defaults — only change them if you know you want to.

## 3. Run the backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The API is now at `http://127.0.0.1:8000` (interactive docs at
`http://127.0.0.1:8000/docs`). On first use it will download the
`all-MiniLM-L6-v2` sentence-transformers model (~90 MB) automatically —
this needs an internet connection once; it's then cached locally
(`~/.cache/huggingface`) for all future runs. If the model can't be
downloaded (offline, blocked network), SubFit still works — it degrades
gracefully to rule/vocabulary-only checks and just skips the semantic
similarity score.

## 4. Run the frontend

In a second terminal, from the project root:

```bash
cd frontend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

This opens the SubFit UI at `http://localhost:8501`. It expects the backend
at `http://127.0.0.1:8000` by default — change it in the sidebar, or set
`SUBFIT_BACKEND_URL`, if you're running the backend elsewhere.

## Using SubFit

### Subreddit Setup tab

1. Enter a subreddit name (no `r/` prefix) and pick how many posts to
   sample (2,000–5,000).
2. Click **Fetch / Refresh corpus**. SubFit will:
   - Fetch subreddit metadata (subscribers, NSFW/quarantine flags).
   - Fetch published subreddit rules.
   - Try to fetch a public AutoModerator wiki config, if one exists.
   - Sample live posts from `/new`, `/hot`, `/rising`, and `/top` (year and
     all-time), de-duplicated, sequentially (never concurrently, to
     respect Reddit's rate limits — PRAW handles the actual throttling).
   - Compute a sentence embedding for each post and cache everything in
     SQLite.
3. The corpus freshness timestamp and cached-subreddit list let you see at
   a glance what's cached and re-fetch (refresh) any time.

Private, banned, quarantined, not-found, and empty subreddits are all
handled gracefully — SubFit records why the fetch didn't yield a corpus
instead of crashing, and the Draft Checker will surface that status
instead of a score.

### Draft Checker tab

1. Paste your draft title/body.
2. Select one or more already-fetched subreddits (or type extra names —
   you'll be told to fetch them first if they aren't cached).
3. Click **Check draft**. For each subreddit you get:
   - An overall **risk score** (0–100) and level (low/medium/high).
   - Any **explicit AutoModerator/rule keyword hits**, quoting the
     matched rule and its configured action.
   - **Highlighted terms/phrases** that are statistical outliers versus
     the subreddit's normal vocabulary (absent = red-flagged hardest, rare
     = flagged softer), plus a semantic/topical similarity score.
   - A plain-English list of the top 2–3 concerns.

If a subreddit has no public AutoModerator config, SubFit says so
explicitly ("no explicit rule list available for this sub, showing
vocabulary-fit analysis only") rather than guessing or failing.

### Saved Drafts tab

Save a draft with an optional name, revisit it later, load it back into
the Draft Checker, or delete it — handy when you're deciding which of
several subreddits (or several draft phrasings) to post to.

## How the risk score works

This is a transparent heuristic, not a trained/calibrated model:

- An explicit AutoModerator/rule keyword hit always pushes risk to **high**
  and contributes the most to the numeric score.
- Vocabulary outliers (words/phrases that are rare or entirely absent from
  the subreddit's sampled corpus) contribute next.
- Topical/semantic drift (low cosine similarity between your draft's
  embedding and the corpus's embeddings) contributes least.

You can tune the weights in `backend/app/scoring.py` if your judgment
differs — the formula is intentionally simple and inspectable rather than
a black box.

## Notes & limitations

- **Read-only.** SubFit only ever calls PRAW's read-only endpoints. It
  cannot and does not post, comment, vote, or message on your behalf.
- **No historical removal data.** Because Reddit no longer exposes
  removed/banned post history, SubFit approximates "fits the sub" using
  what's *currently live* plus published rules/AutoMod config. It's a
  heuristic signal, not a guarantee your post won't be removed.
- **AutoModerator config parsing is best-effort.** Configs are freeform
  YAML with custom modifier syntax; SubFit parses common patterns (title
  /body/flair triggers, `regex`/`word` modifiers) and falls back to a
  lower-confidence heuristic extraction if a page isn't valid YAML.
  Domain/URL/flair-only rules are not checked against a text-only draft
  since there's no link/flair context to match against.
- **Rate limits.** Corpus fetches pull from multiple Reddit listings
  sequentially (never concurrently); PRAW handles Reddit's own
  throttling automatically.

## Tests

A small smoke-test suite covers the Reddit-parsing logic that doesn't
require live credentials:

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest tests -q
```
