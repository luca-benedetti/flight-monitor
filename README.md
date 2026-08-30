# BRU ⇄ VCE Flight tool

Find round trips between Brussels (BRU) and Venice (VCE): a free iOS home-screen
widget plus a small web app, both reading the same weekly-fresh dataset of
one-way direct flights.

```
                    every week (GitHub Actions cron, free)
  Google Flights ──▶ build-fares (Playwright) ──▶ fares.json ──▶ GitHub Pages
       nonstop offers                                   │
                                                        ├─▶ web app  (filters + results)
                                                        └─▶ Scriptable iOS widget
```

The data side fetches **all nonstop offers for the next 5 months** (both
directions) and serves one static file. All filtering/ranking happens on the
client (web app and widget), so you can play with conditions without touching
the data pipeline.

## Repo layout

```
flight_monitor/         Python: scraper fetcher, fares builder, round-trip ranker
  fetchers/scraper.py     live Google Flights scraping (fast-flights + Playwright)
  build_fares.py          builds fares.json over a horizon, with cache/resume
  find_round_trips.py     Python reference ranker (mirrors web/filter.js)
  flight_model.py         JSON schema + validator
web/                    static web app (index.html + filter.js)
widget/                 Scriptable widget script (flight-widget.js)
.github/workflows/fares.yml   weekly cron + Pages publish
```

## Data pipeline

### `build-fares` — fetch the whole horizon

Scrapes every nonstop flight per day for **start (default: tomorrow) → +5
months**, both directions, no time/airline filtering at scrape time (all that
lives in the client filters):

```
uv run build-fares                    # default horizon, nonstop pass only
uv run build-fares --horizon 6        # longer horizon
uv run build-fares --with-connections # also merge an all-offers pass
uv run build-fares --dates 2026-09-05,2026-09-08   # smoke test
```

Resilience:

- Per-day results are cached in `data/fares_cache/` (one JSON per
  direction/day) and reused on re-runs → an interrupted or partial run resumes
  instead of restarting.
- Each day retries (`--retries`, default 2 extra attempts) on transient
  parser/network errors.
- A day that still fails is skipped and **listed**; the partial dataset is
  still published with `metadata.skipped_days`. The run only aborts if every
  day of a pass fails (i.e. blocked).
- Weekly CI caches `data/fares_cache` via `actions/cache` so a failed runner
  run resumes on the next dispatch.

### `find-round-trips` — CLI ranker (mirrors the web engine)

Pairs outbound/return legs and ranks by **price**. Its semantics are identical
to `web/filter.js` (verified: same output on the same data) so the CLI is a
debugging/reference tool for whatever the widget/web show.

```
uv run find-round-trips --data data/fares.json --min-nights 4 --max-nights 10
uv run find-round-trips --dep-weekdays 1,4 --dep-after-hour 17   # Mon/Thu evening
uv run find-round-trips --search-from 2026-12-01 --search-to 2027-01-31
```

Flags: `--min-nights/--max-nights`, `--saturday-in/--no-saturday-in`,
`--nonstop/--no-nonstop`, `--airlines`, `--earliest-departure HH:MM`,
`--dep-weekdays 0=Sun..6=Sat`, `--dep-after-hour 24h`, `--search-from/to`,
`--force-include-day YYYY-MM-DD`.

## Web app

`web/index.html` + `web/filter.js`, served on the same Pages site. Open
`https://luca-benedetti.github.io/flight-monitor/` and you get:

- Trip shape: min/max nights, Saturday-in, nonstop, airlines, earliest departure.
- "Leave" filters: allowed weekdays (Sun–Sat), depart-at/after hour,
  departure date window.
- "Must cover": force trips to span a specific day.
- Live result table (price, dates, legs), with a freshness + skipped-days
  warning.

## iOS widget

`widget/flight-widget.js` (Scriptable). Edit the `CONFIG` block at the top to
set the same knobs (min/max nights, Saturday-in, nonstop, `depWeekdays` /
`depAfterHour` for "Monday/Thursday evening", `searchFrom/searchTo`,
`forceIncludeDay`), save in the Scriptable app, add as a home-screen widget.
The widget fetches `fares.json` **and** the shared `web/filter.js` engine from
the Pages URL and scores locally.

Because scoring runs on-device with your own constants, a second person (girlfriend
phase) just installs the same script/app with different constants — zero new
infrastructure.

## Current state

- Live scrape verified: **494 nonstop offers / 167 days** (both directions),
  published weekly + on demand.
- One known date is deterministic-flaky: `2026-09-20 VCE→BRU` trips the
  fast-flights parser (`'NoneType' object is not subscriptable`); it's reported
  via `metadata.skipped_days` and the widget/web show the missing-day warning.
- JS engine and Python ranker produce **identical** trip lists across knob
  combinations (parity-checked).

## Backlog / future ideas

- Store a per-day *scan timestamp* with each cached result, so a horizon can be
  fetched in several sessions with per-day staleness instead of one
  `generated_at`.
- Investigate the `2026-09-20 VCE→BRU` page variant.
- More widget results (list-screen / per-weekend view).