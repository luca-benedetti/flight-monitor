# Deployment Plan — BRU ⇄ VCE flight widget (Scriptable path)

Personal project. Zero budget, zero Apple-developer friction, widget on the home
screen, parameters editable from the phone. Companion of README.md — this is
about *how it runs in the real world*, not how the Python scoring works.

## Non-negotiable requirements

- Free, no server to maintain.
- A **home-screen widget** showing the top round trips.
- No Xcode, no Apple Developer account, no 7-day re-signing (native iOS apps are
  out — a home-screen widget demands a native app, which on a free account must
  be re-signed every 7 days; the only escape hatches were $99/yr TestFlight or
  not going native — see decisions below).
- Config changed from the phone, without touching the Mac.
- Later: same thing for a second person (girlfriend) with a different config.
- Notifications are out of scope.

## Selected architecture: "server serves fares, Scriptable does the thinking"

The insight that shapes everything: the personal part of this project
(false constraints, scoring, ranking) is a **pure, config-driven function** —
`find_round_trips.py`. It never needed a server. It was "ported to the cloud"
by assumption.

So we split the workload:

```
 WEEKLY (free, server-side)                     ON THE PHONE (free, per user)
 ┌─────────────────────────────┐
 │ GitHub Actions (cron)       │
 │  fetch fare GRID (date-grid)│       ┌──────────────────────────────────┐
 │  write fares.json (one-way) │       │ Scriptable JS widget             │
 │  (brand-new raw legs only,  │──────▶│  - reads fares.json from a URL   │
 │   no config inside)         │       │  - runs scoring (JS port)        │
 └─────────────────────────────┘       │  - shows top trips               │
                                       │  - params at top of the script   │
                                       │  - per-user, per-phone           │
                                       └──────────────────────────────────┘
```

- The cloud stores only one fact: *what do BRU⇄VCE one-way legs cost over the
  horizon right now*. Same artifact for every user. No config, no profiles, no
  regeneration API.
- Everything personal runs on the device. It's a widget over a while-loop of a
  few thousand combinations — trivial for the phone.

## Server side (the only moving part)

Purpose: keep `fares.json` (one-way legs, both directions, full horizon) fresh.

1. **Data source**: live Google Flights scrape via `fast-flights` v3 (see
   "Step 2 result"). Per-date requests (≈25–35/wk with filters); no key, no
   quota. Runs on the Mac or in a headless GitHub Actions runner (needs
   Playwright + Chrome binary provisioned in the job; consent is accepted once
   per browser session).
   - Fallbacks: RapidAPI `google-flights8` BASIC tier (per-date) or mock data.
2. **Scheduler**: GitHub Actions cron (free, ~weekly). Stores the RapidAPI key
   as a secret, never in the repo.
3. **Serving**: static JSON. GitHub Pages (repo branch or `/docs`) or a 3-line
   Cloudflare Worker. The widget fetches one stable URL.
4. **Mock mode stays**: `generate_mock_flights.py` keeps producing
   `mock_flights_BRU_VCE.json` so the whole pipeline runs with zero cost and
   zero API when needed.

Open question: exact free-tier volume of `google-flights8` BASIC
(comparable scrapers sit at ~150 req/month — with date-grid that's plenty for
a weekly full-window refresh). Confirm on the RapidAPI listing page.

### Step 1 result (tested 2026-08-30 with key)

`date-grid/one-way` was probed live (`explore_date_grid.py`): **returns an empty
`entries[]` grid for BRU→VCE** in every variant (default ±3d window, explicit
15-day window, near-term dates), and it also echoes back a `currency` that
ignores the request (EUR → USD). So it's a dead end even for a "cheapest day"
widget on this route/API version. The endpoint is both schema-limited and
empirically broken here.

### Free/cheap sources for RICH data (full offers, tested candidates)

The scorer needs per-flight detail (times, airline, stops, duration), which
rules out price-grid-only endpoints. Free paths that keep the full model:

| Source | Rich data? | Request efficiency | Free? | Real prices? | Risk |
|---|---|---|---|---|---|
| **Kiwi Tequila `/v2/search`** | ✅ full itineraries (legs, airline, times, stops, price) | ✅ date-range in one call (`date_from/date_to`, `one_per_date`, `limit` up to 1000) | ⚠️ portal key historically free; some 2024+ reports say new signups invitation-only — must try | ✅ | join-wall may block |
| Google Flights scraping (`flights_ice_breaker.py`, or `swoop`) | ✅ | per-date | ✅ | ✅ | ToS-grey, breakable, anti-bot |
| SerpAPI google_flights | ✅ | per-date | ~100/mo | ✅ | quota tiny |
| Amadeus self-service free tier | ✅ | per-date | ✅ | ❌ sandbox fake fares | useless for real pricing |
| RapidAPI `/api/v1/search` | ✅ | per-date (≈306/horizon) | BASIC ~150/mo | ✅ | quota too small for 5 mo |

**Step 1 → decision: scraper is the primary data path.** Free APIs are closed
(Amadeus self-service decommissioned 2026-07, Tequila invite-only since 2024,
RapidAPI `date-grid` returns 0 entries for BRU→VCE — tested). `fast-flights`
(v3, AWeirdDev/flights, MIT, maintained) replays Google Flights' request format:
no key, rich structured offers, built-in filters (airlines/max_stops/dep-hours),
~1–3 s/request → ~25–35 requests ≈ 1–2 min per constraint-driven weekly run.

### Step 2 result (tested 2026-08-30 with live data, no mock)

Scraper fetcher implemented and proven end-to-end:

- `flight_monitor/fetchers/scraper.py` (`ScraperFetcher`) + CLI `scrape-flights`.
- ⚠️ EU geo ⇒ Google serves a **consent wall** ("Before you continue"): raw
  primp/impersonation (and consent-cookie injection) gets blocked. Solved by
  rendering the page in headless **Playwright** (`chromium`, `channel="chrome"`,
  system Chrome) and clicking "Accept all". Consent is accepted once per session.
- 10-day live run (BRU→VCE + VCE→BRU, 2026-08-31..09-09): **130 real offers,
  121–737 EUR**; red-eyes captured with `arrival_day_offset=1`.
- Constraint filters proven: `--max-stops 0 --earliest/latest-departure-hour`
  narrow to nonstop SN/etc. per-day.
- Merged both directions → `find-round-trips --no-nonstop` computed real trips
  (best 208 EUR: out Sep 1, back Sep 8, 7 nights); dataset validates via
  `flight_model.py`.
- `fast-flights` pinned `==3.1.0` (v2 `FlightData`/fallback modes are gone —
  `flights_ice_breaker.py` removed as superseded). v3 needs Python ≥3.10 →
  `requires-python` bumped. Also adds `typing_extensions` (upstream packaging gap).
- No mock: a failing day hard-fails the run with a per-day report.

### Step 3 result (fares artifact + widget, local)

- `flight_monitor/build_fares.py` (`build-fares`): derives the **scorable date
  set** from `config/round_trip_config.json` (outbound = period dates, return =
  outbound + min..max nights; 2026-09-01..01-31 → 153 outbound / 163 return
  dates) and runs 4 scrapes: each direction full + nonstop pass. Merges,
  dedupes (cheapest per identical leg), renumbers ids, recomputes `is_best`,
  validates → single `data/fares.json` artifact.
  - The nonstop pass is essential: default Google listings omit direct
    VCE→BRU legs (verified: 0 nonstop in the default scrape, ~2/day with
    `max_stops 0`).
  - Full weekly run ≈ 630 requests ≈ 40–60 min (default delay 1.5 s). Smoke
    test on a 4-date set verified merge/dedupe/validate + scorer end-to-end.
- `widget/flight-widget.js` (Scriptable): direct JS port of the scorer. Config
  block at the top (nonstop/airlines/saturday-in/periods+penalties),
  fetches `fares.json` from a static URL, scores locally, renders top trips.
  **Verified against the Python reference on the same input: identical result**
  (052→Sep-10, 5n, 748 € = 727 + 21 penalties).
- ⚠️ Google may throttle a 630-request burst: keep the weekly cadence, stagger
  with the poll delay, and treat a hard failure as data-not-refreshed (keep the
  previous fares.json), not a broken widget.

## Phone side (Scriptable)

- Free App Store app, installable by anyone without any Apple-developer stuff.
- One JS file = the whole "app": fetch fares URL → score with the current
  config → render top trips in the widget.
- The JS is a small, direct port of the scoring core in `find_round_trips.py`
  (hard/soft constraints, per-period config, `score = price + penalties`,
  `overall_best` + per-weekend top). Pure and serialisable, ~a couple hundred
  lines.
- **Config from the phone**: the first lines of the script are the constants
  (origin/destination, min–max nights, Saturday-in, earliest departure,
  penalties). Edit in the Scriptable app, save, widget re-renders. No Mac, no
  redeploy.
- Sync via iCloud so the script persists across reinstallation/resigning.
- The JSON schema must stay locked while the Python and JS sides diverge:
  reuse it from `flight_model.py`; only convert the leg fields the widget
  needs, browser into readable text in the widget.

Honest constraints:
- Widget refresh timing is decided by iOS, not by the script (order of
  minutes–hours depending on background status). Fine for weekly-fresh data.
- No standalone app UI or push notifications — intentionally accepted.

## Girlfriend (phase 2)

- Same free app, same script (or a copy) with her constants.
- Because all logic is per-device, a second user costs zero infrastructure.
- Real remaining cost: *teaching* her to edit two numbers if she ever wants to
  change them — keep the constant block documented at the top of the script.

## Rollout phases

1. **Verify data** ✅ done: `date-grid` returns 0 entries for BRU→VCE (dead
   end); scraper fetcher proven live over 10 days (Step 2 result) — rich
   scoring kept, free.
2. **Server** ✅ workflow implemented: `.github/workflows/fares.yml` — weekly
   cron (Mon 05:00 UTC) + manual dispatch; provisions uv/Python 3.12 + Chrome
   on the runner, `build-fares --out docs/fares.json`, validates, publishes
   `docs/` to the `gh-pages` branch (peaceiris/actions-gh-pages). GitHub Pages
   then serves `https://luca-benedetti.github.io/flight-monitor/fares.json` —
   paste that into the widget's `CONFIG.faresUrl`.
   - One-time manual step (repo Settings → Pages → deploy from branch
     `gh-pages` / root), then run the workflow once (`workflow_dispatch`) to
     confirm scraping works on the runner (consent/blocking risk lives here —
     first successful CI run is the real proof).
3. **Phone** (built, needs testing on device): `widget/flight-widget.js` in
   Scriptable; add as home-screen widget; config block at top. Edit-and-save to
   change rules.
4. **Polish**: per-weekend view line, cheapest 30 list screen? Widget only, no
   built-in app UI — keep it a widget.
5. **GF**: copy the script, change constants, done.

## What was decided and what's still open

| Decision | Status |
|---|---|
| Native iOS app (SwiftUI + widget) | ❌ rejected — 7-day resign friction |
| $99 Apple Developer + TestFlight | ❌ rejected — fee, not needed now |
| HuggingFace Spaces + FastAPI | ❌ rejected — heavier than needed, no cron, sleeps |
| GitHub Actions + Pages for fares | ✅ 
| Scriptable JS widget on the phone | ✅ 
| Config from the phone (script constants) | ✅ 
| GF support via same script | deferred to phase 5 |
| Real data via free `date-grid` tier | ❌ tested — endpoint returns 0 entries |
| Rich data free | ✅ scraper path chosen and proven: `ScraperFetcher` (fast-flights v3 + Playwright), 10-day live test passed |
| Notifications | ❌ out of scope |

## Hands-on next steps

1. Commit the new files and push, so CI can run (`un`: `pyproject.toml`,
   `PLAN.md`, `flight_monitor/build_fares.py`, `widget/`, `.github/`).
2. Enable Pages for the `gh-pages` branch and dispatch the
   **fares** workflow once; watch the first Google-block risk pass.
3. Open `widget/flight-widget.js`, uncomment/paste the Pages `faresUrl`, and
   test in Scriptable on the phone.
4. Local Mac run (`uv run python -m flight_monitor.build_fares`) remains an
   option for immediate/adhoc refreshes without waiting for CI.

## Reminders / gotchas

- The API key and any secrets live only in GitHub Actions secrets, never in
  the repo or the widget.
- `fetch_flights.py`'s other Google Flights endpoints must not be confused
  with the price API; the grid endpoints are what makes "free" viable.
- The whole thing stays mock-compatible: no feature should require the paid
  API to work locally.