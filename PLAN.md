# Deployment Plan — BRU ⇄ VCE flight tool (web app + Scriptable widget)

Personal project. Zero budget, zero Apple-developer friction. Companion of
README.md — this is about *how it runs in the real world*, not how the Python
scoring works.

## Non-negotiable requirements

- Free, no server to maintain.
- A **home-screen widget** showing the top round trips.
- A **web app** where I can easily add/change filter conditions and inspect
  results.
- No Xcode, no Apple Developer account, no 7-day re-signing (native iOS apps
  are out — a home-screen widget demands a native app, which on a free account
  must be re-signed every 7 days; the escape hatches were $99/yr TestFlight or
  not going native — rejected).
- Config changed from the phone or the browser, without touching the Mac.
- Later: same thing for a second person (girlfriend).

## Architecture: "server serves fares, clients do the thinking"

The cloud stores only one fact: *what do BRU⇄VCE one-way legs cost over the
horizon right now* (all nonstop offers, next ~5 months, both directions). No
filters, no profiles, no config server-side.

```
 WEEKLY (free, server-side)                          CLIENTS (free, per user)
 GitHub Actions cron ─▶ fares.json ─▶ GitHub Pages ──▶ Scriptable iOS widget
   build-fares (Playwright scrape)                          (web/filter.js engine)
        │  cache + resume (data/fares_cache)           ─▶ web app (fares.json +
        │  metadata.skipped_days for failures)             filter.js, filter UI)
```

- Filtering/ranking is one shared JS engine, `web/filter.js`
  (`computeTrips(flights, options)`) used by BOTH the widget and the web app,
  so results always match. Pure, no I/O.
- The Python ranker `find_round_trips.py` mirrors `web/filter.js` exactly
  (parity-checked: identical trip lists on the same data across all knob
  combinations) — used as a CLI/reference on the Mac.
- Ranking is **price only** (ties: longer trip, then earlier departures).
  No penalty weights — hard filters answer "what I want to see".

## Filter knobs (shared everywhere)

| Knob | Meaning |
|---|---|
| `searchFrom` / `searchTo` | outbound departure window ("" = whole horizon) |
| `minNights` / `maxNights` | trip length range |
| `nonstopOnly` | direct flights only |
| `airlines` | comma-separated name substrings (e.g. "SN") |
| `saturdayIn` | require a Saturday night in the trip |
| `earliestDeparture` | drop any leg leaving before HH:MM |
| `depWeekdays` | outbound only: leave on these weekdays (0=Sun..6=Sat) |
| `depAfterHour` | outbound only: leave at/after this hour (24h) |
| `includeFrom` / `includeTo` | trip must span the range: leave on/before `includeFrom`, return on/after `includeTo` |

## Data pipeline (server)

1. **Source**: live Google Flights scrape via `fast-flights` v3 + Playwright
   (headless system Chrome, accepts Google's EU consent wall once/session).
   `ScraperFetcher` in `flight_monitor/fetchers/scraper.py`. No API key.
2. **Builder**: `flight_monitor/build_fares.py` (`build-fares`) scrapes every
   nonstop offer per day over a horizon — start default tomorrow, `--horizon 5`
   months, both directions, no time/airline filtering at scrape time
   (`--with-connections` optionally merges an all-offers pass). One artifact.
3. **Scheduler**: GitHub Actions cron (weekly Mon 05:00 UTC) + manual dispatch.
   Publishes `docs/` (fares.json + web app) to the `gh-pages` branch.
4. **Resilience / resume**:
   - Per-day results cached in `--cache-dir data/fares_cache` (one JSON per
     direction/day), reused on re-runs → interrupted/partial runs resume.
   - Days retry (`--retries`, default 2) on transient parser/network errors.
   - Skipped days are listed and the partial dataset is still published with
     `metadata.skipped_days`; the run only aborts if every day of a pass fails.
   - First CI run failed because a single parser TypeError (2026-09-20 VCE→BRU
     nonstop) killed the whole build — this is what the cache/partial handled.
   - CI also caches `data/fares_cache` (actions/cache) so a failing run resumes
     on the next dispatch.

### Verification (live, no mock)

- 10-day probe BRU⇄VCE: 130 real offers (121–737 EUR), consent-wall solved.
- Full weekly run (nonstop-only): ≈320 requests ≈ 20–25 min → **494 nonstop
  offers / 167 days**, both directions, published weekly.
- Known deterministic flake: `2026-09-20 VCE→BRU` trips fast_flights'
  `'NoneType' object is not subscriptable` → surfaced via `skipped_days`
  (widget/web show "n date(s) missing"); everything else scrapes cleanly.

## Phone side (Scriptable)

- One script `widget/flight-widget.js`: edit `CONFIG` at the top, save in the
  Scriptable app, add as a home-screen widget. Konfig: min/max nights,
  saturday-in, nonstop, earliest departure, depWeekdays/depAfterHour
  ("Monday/Thursday evening"), searchFrom/searchTo, includeFrom/includeTo.
- The widget fetches the shared engine from the Pages URL (`engineUrl` →
  `filter.js`) and `fares.json`, then scores locally.
- Footer shows data freshness + "n date(s) missing from scan (partial data)"
  when the build skipped days.
- Widget refresh timing is decided by iOS (minutes–hours). Fine for
  weekly-fresh data.
- GF phase: same app/script with her constants — zero new infrastructure.

## Web app

- `web/index.html` + `web/filter.js`, published to the Pages site root →
  `https://luca-benedetti.github.io/flight-monitor/`.
- Form for every knob + live result table (price, dates, legs, Sat night),
  freshness + skipped-days warning.

## Status

- ✅ Pipeline end-to-end: scrape → fares.json → Pages (weekly cron + manual).
- ✅ Widget tested on phone (v1).
- ✅ Web app (filter UI) built, published with the fares workflow.
- ✅ JS engine ≡ Python ranker (parity-checked).
- 🔜 Re-dispatch the fares workflow so Pages serves the new web app + engine.

## Backlog / future ideas

- Per-day *scan timestamp* per cached date → split a horizon across sessions,
  staleness per date instead of one global `generated_at`.
- Investigate the `2026-09-20 VCE→BRU` page variant.
- Web app: persist last-used filters (localStorage), shareable URL params.
- Widget: list-screen / per-weekend view (medium+ widget rows).

## Reminders / gotchas

- One scraper session must not run while another does (Chrome + Google load);
  the Actions workflow uses `concurrency` so weekly cron and manual dispatch
  serialise.
- Keep the scrape unfiltered (all nonstop, every time); push conditions into
  `web/filter.js` / the Python mirror — single source of truth.
- Repo is private; GitHub Pages on free plan requires a public repo (repo is
  the one open decision). No secrets live in the repo or the widget either way.