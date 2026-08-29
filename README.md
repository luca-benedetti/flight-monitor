# BRU ⇄ VCE Flight Price Tool

Find round-trip flight combinations between Brussels (BRU) and Venice (VCE),
understand what they cost, and rank them against personal preferences — without
burning limited API requests while the logic is still being developed.

## Goal

The end product: given a calendar horizon (e.g. "the next 5 months"), enumerate
one-way and round-trip flight options on BRU ⇄ VCE and surface the ones that
matter to the user. "Matter" is deliberately user-defined — cheap trips, trips
that include a Saturday night, trips of a certain length, trips at civilised
departure times — expressed as **hard constraints** (impossibilities) and
**soft constraints** (preferences that cost a tunable penalty).

## Why this design

A few decisions shape the whole project:

1. **Mock-first.** The real API key is rate-limited, so everything except the
   actual fetching runs against deterministic, locally generated data. The
   algorithm is developed and tuned on `mock_flights_BRU_VCE.json` and works
   unchanged on real fetched data later.
2. **One data model.** Both the live fetcher and the mock generator emit the
   same JSON schema (`flight_model.py`), so "does it work" is answerable by one
   validator instead of drifting formats.
3. **Server-side filtering.** The API supports `max_stops` and
   `preferred_airlines`, so filters worth enforcing upstream are sent with the
   request instead of wasting results.
4. **Score = price + penalties.** Hard vs soft constraints is a false
   dichotomy — it is a matter of weight. One formula, `score = price +
   early_departure_penalty + short_stay_penalty`, tunes behaviour by editing
   numbers (config) instead of code.
5. **Per-period constraints.** Preferences are not constant over a year, so
   constraints can differ per calendar window (e.g. longer stays around the
   winter holidays).

## Data model

Every record is a **one-way flight offer** (`flight_model.py`):

```json
{
  "flight_id": "BRU-VCE-2026-09-15-003",
  "origin": "BRU",
  "destination": "VCE",
  "date": "2026-09-15",
  "airline": "Brussels Airlines",
  "departure": "15:40",
  "arrival": "17:25",
  "arrival_day_offset": 0,
  "duration_min": 105,
  "stops": 0,
  "price": 119.0,
  "currency": "EUR",
  "is_best": false
}
```

A dataset wraps them in `metadata` + `flights`. Conventions:

- `departure` / `arrival` are local `HH:MM`; `arrival_day_offset` is 1 for
  red-eyes that land the next day.
- `price` is a **number** (never a string) so it can be compared directly.
- Round trips are *not* precomputed in the data — the finder pairs legs.

Validate any dataset (mock or real):

```
python flight_model.py mock_flights_BRU_VCE.json
```

## Pipeline

```
                    ┌─────────────────────────┐
   RapidAPI key  → │  fetch_flights.py        │ → flights_BRU_VCE.json
   (.env)          └─────────────────────────┘
                    ┌─────────────────────────┐
                  → │  generate_mock_flights.py│ → mock_flights_BRU_VCE.json
                    └─────────────────────────┘
                    ┌─────────────────────────┐
   flights*.json  → │  flight_model.py        │  (validator, shared schema)
                    └─────────────────────────┘
                    ┌─────────────────────────┐
   mock/flights +  →│  find_round_trips.py    │ → round_trips.json
   round_trip_config.json                     │    (overall best + top-k/weekend)
                    └─────────────────────────┘
```

### `fetch_flights.py` — live data

- Calls RapidAPI **google-flights8** (Crawlio), `GET /api/v1/search`
  (one-way search).
- Query params sent: `origin`, `destination`, `date`, `adults=1`,
  `seat_class=economy`, `currency=EUR`, plus optional
  `max_stops` (`--max-stops 0|1|2`) and `preferred_airlines`
  (`--airlines SN` or e.g. `STAR_ALLIANCE`).
- The API returns a top-level dict with `flights[]` / `results[]`; each row
  carries times under `departure` / `arrival` (top-level and per segment),
  `duration` + `duration_min`, `stops`, `price`, and its own `is_best`.
  The parser maps those onto the model fields.
- Output is capped to the first 10 rows (`flight_lists[:10]`) — a client-side
  choice, not an API limit.
- Reads the key from `RAPIDAPI_KEY` (env var or `--key`). The project's `.env`
  also has `TRAXES_*` credentials used by `script.py`, which is unrelated.

```
python fetch_flights.py --from BRU --to VCE --dates 2026-09-15 --max-stops 0 --airlines SN
python fetch_flights.py --from BRU --to VCE --dates 2026-09-15 --sample   # no key needed
```

### `generate_mock_flights.py` — offline data

- Builds a deterministic (fixed seed) dataset of one-way legs, both directions,
  from itinerary templates (Brussels Airlines nonstops, 1-stop via EU hubs,
  budget red-eyes, cheap 2-stops).
- Current mock: **5202 flights**, 153 days (`2026-09-01 .. 2027-01-31`), 17
  departure times/day/direction, prices ≈ €87–€299.
- Weekend prices are inflated slightly; prices vary per date via seeded RNG so
  the finder has something to chew on.

```
python generate_mock_flights.py --dates 2026-09-01..2027-01-31
```

### `find_round_trips.py` — the enumerator & ranker

Pairs every qualifying BRU→VCE outbound leg with a qualifying VCE→BRU return leg
and scores the result. No API calls.

**Score formula**

```
score = price + early_departure_penalty + short_stay_penalty
```

**Hard constraints** (legs/combos removed before scoring):

| Constraint | Meaning | CLI |
|---|---|---|
| Nonstop only | drops legs with `stops > 0` | on by default; `--no-nonstop` |
| Airline list | substring match on airline name | `--airlines` |
| Min / max nights | stay length between legs | `--min-nights`, `--max-nights` (defaults 4–12) |
| Earliest departure | legs leaving before `HH:MM` are dropped | `--earliest-departure` |
| Saturday night in | the stay must cover a Saturday night | `--saturday-in` (default); `--no-saturday-in` |

**Soft constraints** (penalties added to the score):

| Constraint | Penalty | CLI |
|---|---|---|
| Early departure | € per minute the leg leaves before `preferred-departure` | `--preferred-departure`, `--early-departure-penalty` |
| Short stay | € per night below `preferred-nights` | `--preferred-nights`, `--short-stay-penalty` |

A large penalty weight effectively hardens a soft constraint; a zero weight
disables it.

**Periods** — `--config round_trip_config.json` lets every constraint above
differ per calendar window (outbound date picks the period). CLI flags act as
defaults that a period can override. Example config ships as
`round_trip_config.json` (Sep–Nov: 4–10 nights, no flights before 08:30;
Dec–Jan: 5–14 nights, prefer longer stays).

**Output** — `round_trips.json` and console summary:

- `overall_best`: cheapest `--limit` (default 30) round trips by score.
- `per_weekend_top`: `--top-k` (default 5) trips per Saturday-night group,
  so you get "the useful few" per weekend rather than thousands of rows.

```
python find_round_trips.py                                   # defaults
python find_round_trips.py --config round_trip_config.json
python find_round_trips.py --min-nights 5 --max-nights 9 --top-k 3 --limit 10
```

## Current state

Working end-to-end and verified:

- [x] One-way fetch from the real API, server-side `max_stops`/`preferred_airlines`
      filtering, output validates against the model.
- [x] Shared data model + JSON validator.
- [x] Deterministic 5-month mock dataset (both directions, mixed airlines/times).
- [x] Round-trip enumeration with hard + soft (weighted) constraints and
      per-period configuration.

Numbers from recent runs on the mock:

- Default config (Saturday-in, 4–12 nights, nonstop): **≈29 450** valid round
  trips over the 5-month window.
- Cheapest trip overall ≈ **€174** (e.g. 16→24 Dec, 8 nights).
- Adding a hard `earliest_departure` of 08:30–09:00 removes every 06:30 leg;
  weighting `preferred-nights 10 @ 30 €/night` demotes cheap short trips in
  favour of 10–12-night stays.

## Extending

New preferences slot into the existing pattern:

1. **Hard**: add a `leg_hard_ok` / combo filter in `build_combo_candidates`.
2. **Soft**: add a penalty function called from `penalize()` so it lands in
   `combo["penalties"]` and feeds the score.

Suggested next candidates: a latest nightly arrival for legs, a hard total
budget cap, per-night price view, or a "no wasted Saturday at home" rule.