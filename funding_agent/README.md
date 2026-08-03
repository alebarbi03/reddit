# Tech.eu funding agent

Every morning: reads the [Tech.eu Funding Explorer](https://funding.tech.eu/),
tells you **who raised, how much, what they do, and who led the round**, and
writes ready-to-publish LinkedIn posts with **5 companies per post**.

Runs entirely on your machine. It is read-only on the web and never posts
anything anywhere — the posts land as text files for you to review and paste.

```
Tech.eu funding brief — Mon 03 Aug 2026
6 new rounds · €93M disclosed

1. Solaris Grid — €21M (Series A)
   What they do : Software for balancing renewable energy grids.
   Lead investor: Cherry Ventures

2. Aurora Robotics — €42M (Series B)
   What they do : Warehouse robots that pick and pack grocery orders.
   Lead investor: Northzone
   ...
```

## Install

```bash
cd funding_agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium      # the Explorer is a JS app
```

Playwright is strongly recommended but optional — `run --no-browser` falls back
to plain HTTP, and the agent falls back again to the tech.eu RSS feed if the
Explorer can't be read at all.

## Use

```bash
python -m app.cli run                 # the morning job
python -m app.cli run --dry-run       # same, without marking rounds as seen
python -m app.cli run --per-post 5 --max-posts 2
python -m app.cli run --min-amount 5000000    # only rounds ≥ €5M
python -m app.cli run --all           # re-include rounds from earlier runs
python -m app.cli latest              # reprint the last brief
```

Each run writes to `out/YYYY-MM-DD/`:

| File | Contents |
|---|---|
| `digest.md` | The brief as a table, plus every post |
| `linkedin-1.txt`, `linkedin-2.txt`, … | One post each, paste-ready |

Rounds already reported are recorded in `data/funding.db`, so tomorrow's brief
only contains companies you haven't seen. That's what makes it usable daily
rather than a re-run of the same front page.

## Run it every morning

```bash
python -m app.cli schedule install --at 08:00
python -m app.cli schedule status
python -m app.cli schedule uninstall
```

- **macOS** — a launchd agent at `~/Library/LaunchAgents/eu.techeu.funding-agent.plist`
- **Linux** — a systemd user timer (`Persistent=true`, so a run missed while the
  machine was off happens at next boot). Add `loginctl enable-linger $USER` to
  have it fire when you're not logged in.
- **Anything else** — prints the crontab line to paste.

Both are user-level; no sudo. Logs go to `logs/agent.log`.

## Configuration

Copy `.env.example` to `.env` and edit, or set the variables in your
environment. All are optional.

| Variable | Default | Meaning |
|---|---|---|
| `TECHEU_COMPANIES_PER_POST` | `5` | Companies per LinkedIn post |
| `TECHEU_MAX_POSTS` | `3` | Most posts to produce in one run |
| `TECHEU_LOOKBACK_DAYS` | `3` | Ignore rounds older than this |
| `TECHEU_MIN_AMOUNT_EUR` | `0` | Skip rounds below this size |
| `TECHEU_ONLY_NEW` | `true` | Skip rounds covered on an earlier run |
| `TECHEU_INCLUDE_PARTIAL_POST` | `true` | Emit a final post with fewer than 5 |
| `TECHEU_EXPLORER_URL` | `https://funding.tech.eu/` | Source site |
| `TECHEU_HEADLESS` | `true` | Set `false` to watch the browser work |

## How it reads the Explorer

The Explorer is a single-page app, so its rounds arrive as JSON rather than as
markup. Rather than pin CSS selectors that break on the next redesign, the
agent renders the page and **listens to the JSON the page fetches for itself**,
then finds the array that most looks like funding rounds — records pairing a
company name with an amount and/or investors — and maps fields by name
(`amountEur`, `amount`, `raised`, `company.name`, `lead_investor`, …). Nav
menus, author lists and tag clouds score zero and are ignored.

Sources are tried in this order:

1. XHR/fetch JSON captured from the rendered Explorer
2. JSON embedded in the page (`__NEXT_DATA__`, script tags, RSC flight chunks)
3. Plain HTTP fetch of the same pages
4. The tech.eu RSS feed, parsed from headline grammar
   ("X raises €YM … led by Z")

The feed is also used to fill in descriptions and leads that the Explorer's
table omits.

### If the site changes

```bash
python -m app.cli discover
```

This saves every page and JSON payload the site served to `out/discover/` and
prints their shapes. Add the real field names to the `*_KEYS` tuples in
`app/extract.py` and it picks them up — no other changes needed.

## Tests

```bash
python -m pytest tests -q
```

39 tests, no network required: extraction across several plausible payload
shapes, decoy rejection, amount/date parsing, RSS headline parsing, post
construction, and the de-duplication store.

## Caveats

- **Field mapping is inferred, not contractual.** The heuristics cover the
  shapes an app like this normally serves, but the first live run is worth
  eyeballing — use `discover` if anything looks off.
- **Descriptions are as good as the source.** Where neither the Explorer nor
  the feed says what a company does, the post falls back to its sector.
- **Read the post before publishing.** It's assembled from scraped text; the
  agent deliberately stops at your clipboard.
