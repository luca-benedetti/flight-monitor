#!/usr/bin/env python3
"""
Enumerate and rank round-trip combinations from a flight dataset (mock or
fetched) without spending any API requests.

Constraint model
----------------
Every trip scores  `score = total_price + early_departure_penalty +
short_stay_penalty`.  That one formula is the whole tuning surface:

  * HARD constraints remove options before scoring (impossible trips):
      - nonstop only / airline list
      - min / max nights between outbound and return
      - stay must include a Saturday night (--saturday-in)
      - earliest_departure: legs leaving before HH:MM are dropped

  * SOFT constraints add a monetary penalty, so behaviour is tuned by weight:
      - early_departure_penalty  (euro per minute the leg leaves before
        preferred_departure)
      - short_stay_penalty       (euro per night below preferred_nights)

  Give a soft constraint a huge weight and it behaves like a hard one; drop
  the weight and it just nudges. No code changes needed to change stance.

Periods
-------
Constraints can differ per calendar window (outbound date decides the period),
so you can e.g. allow longer stays around the holidays. Provide a config file:

    python find_round_trips.py --config round_trip_config.json

CLI flags override period defaults; period values override the CLI. Without
--config a single period is used, so plain flags work too:

    python find_round_trips.py --min-nights 4 --max-nights 10 \
        --earliest-departure 09:00 \
        --preferred-departure 10:00 --early-departure-penalty 1.0 \
        --preferred-nights 7 --short-stay-penalty 8.0
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import date, timedelta

from flight_model import Flight, FlightDataset

TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")

PERIOD_KEYS = [
    "from", "to",
    "nonstop", "airlines",
    "min_nights", "max_nights",
    "earliest_departure",
    "preferred_departure", "early_departure_penalty",
    "preferred_nights", "short_stay_penalty",
]

DEFAULT_PERIOD = {
    "from": None, "to": None,
    "nonstop": True, "airlines": "",
    "min_nights": 4, "max_nights": 12,
    "earliest_departure": None,
    "preferred_departure": None, "early_departure_penalty": 0.0,
    "preferred_nights": None, "short_stay_penalty": 0.0,
}


def to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def validate_period(period: dict, index: int) -> None:
    for key in ("earliest_departure", "preferred_departure"):
        value = period.get(key)
        if value and not TIME_RE.match(value):
            raise ValueError(f"period #{index}: {key} must be HH:MM, got {value!r}")
    for key in ("min_nights", "max_nights", "preferred_nights"):
        value = period.get(key)
        if value is not None and value < 0:
            raise ValueError(f"period #{index}: {key} must be >= 0")
    for key in ("early_departure_penalty", "short_stay_penalty"):
        value = period.get(key)
        if value is not None and value < 0:
            raise ValueError(f"period #{index}: {key} must be >= 0")


def load_periods(args) -> list[dict]:
    cli_defaults = {
        k: getattr(args, k) for k in PERIOD_KEYS
        if hasattr(args, k) and getattr(args, k) is not None
    }

    if args.config:
        with open(args.config) as fh:
            loaded = json.load(fh)
        raw_periods = loaded.get("periods") or [loaded]
    else:
        raw_periods = [{}]

    periods = []
    for i, raw in enumerate(raw_periods):
        period = {**DEFAULT_PERIOD, **cli_defaults, **raw}
        validate_period(period, i)
        periods.append(period)
    return periods


def has_saturday_night(depart_date: date, return_date: date) -> bool:
    day = depart_date
    while day < return_date:
        if day.weekday() == 5:
            return True
        day += timedelta(days=1)
    return False


def first_saturday(depart_date: date, return_date: date):
    day = depart_date
    while day < return_date:
        if day.weekday() == 5:
            return day
        day += timedelta(days=1)
    return None


def leg_hard_ok(flight: Flight, period: dict) -> bool:
    if period["nonstop"] and flight.stops > 0:
        return False
    airlines = [a.strip().lower() for a in period["airlines"].split(",") if a.strip()]
    if airlines and not any(a in flight.airline.lower() for a in airlines):
        return False
    if period.get("earliest_departure") and to_minutes(flight.departure) < to_minutes(period["earliest_departure"]):
        return False
    return True


def leg_early_penalty(flight: Flight, period: dict) -> float:
    preferred = period.get("preferred_departure")
    rate = period.get("early_departure_penalty", 0.0)
    if not preferred or not rate:
        return 0.0
    early_minutes = to_minutes(preferred) - to_minutes(flight.departure)
    return max(0, early_minutes) * rate


def short_stay_penalty(nights: int, period: dict) -> float:
    preferred = period.get("preferred_nights")
    rate = period.get("short_stay_penalty", 0.0)
    if not preferred or not rate:
        return 0.0
    return max(0, preferred - nights) * rate


def in_window(day: date, period: dict) -> bool:
    if period["from"] and day < date.fromisoformat(period["from"]):
        return False
    if period["to"] and day > date.fromisoformat(period["to"]):
        return False
    return True


def build_combo(of: Flight, rf: Flight, nights: int, saturday: date | None) -> dict:
    price = round(of.price + rf.price, 2)
    return {
        "outbound": of.to_dict(),
        "return": rf.to_dict(),
        "outbound_date": of.date,
        "return_date": rf.date,
        "nights": nights,
        "saturday_in": saturday.isoformat() if saturday else None,
        "price": price,
        "penalties": {"early_departure": 0.0, "short_stay": 0.0},
        "score": price,
    }


def penalize(combo: dict, olek: Flight, rlek: Flight, period: dict) -> None:
    early = leg_early_penalty(olek, period) + leg_early_penalty(rlek, period)
    short = short_stay_penalty(combo["nights"], period)
    combo["penalties"] = {"early_departure": round(early, 2), "short_stay": round(short, 2)}
    combo["score"] = round(combo["price"] + early + short, 2)


def build_combo_candidates(outbound: list[Flight], inbound: list[Flight], period: dict,
                           saturday_in: bool) -> list[dict]:
    out_by_date: dict[str, list[Flight]] = defaultdict(list)
    ret_by_date: dict[str, list[Flight]] = defaultdict(list)
    for f in outbound:
        if in_window(date.fromisoformat(f.date), period) and leg_hard_ok(f, period):
            out_by_date[f.date].append(f)
    for f in inbound:
        if leg_hard_ok(f, period):
            ret_by_date[f.date].append(f)

    valid_leg_pairs_checked = 0
    combos: list[dict] = []
    for out_date_str, out_flights in out_by_date.items():
        out_date = date.fromisoformat(out_date_str)
        for nights in range(period["min_nights"], period["max_nights"] + 1):
            ret_date = out_date + timedelta(days=nights)
            ret_flights = ret_by_date.get(ret_date.isoformat(), [])
            if not ret_flights:
                continue
            if saturday_in and not has_saturday_night(out_date, ret_date):
                continue
            saturday = first_saturday(out_date, ret_date) if saturday_in else None
            for of in out_flights:
                for rf in ret_flights:
                    valid_leg_pairs_checked += 1
                    combo = build_combo(of, rf, nights, saturday)
                    penalize(combo, of, rf, period)
                    combos.append(combo)
    if valid_leg_pairs_checked == 0:
        print(f"  (period with no valid combos)")
    combos.sort(key=lambda c: (c["score"], c["price"], -c["nights"], c["outbound"]["departure"]))
    return combos


def describe(combo: dict) -> str:
    o, r = combo["outbound"], combo["return"]
    base = (
        f"out {combo['outbound_date']} {o['departure']}-{o['arrival']} "
        f"| return {combo['return_date']} {r['departure']}-{r['arrival']} | {combo['nights']}n"
    )
    parts = [f"price {combo['price']:.2f}"]
    if combo["penalties"]["early_departure"]:
        parts.append(f"early +{combo['penalties']['early_departure']:.2f}")
    if combo["penalties"]["short_stay"]:
        parts.append(f"short +{combo['penalties']['short_stay']:.2f}")
    parts.append(f"score {combo['score']:.2f} €")
    return f"{base} | {'  '.join(parts)}"


def group_by_weekend(combos: list[dict], top_k: int) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for c in combos:
        groups[c["saturday_in"]].append(c)
    return [
        {"saturday": saturday, "combos": groups[saturday][:top_k]}
        for saturday in sorted(groups)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enumerate round trips locally with hard filters and soft-constraint scoring."
    )
    parser.add_argument("--data", default="mock_flights_BRU_VCE.json", help="Input dataset JSON")
    parser.add_argument("--origin", default="BRU")
    parser.add_argument("--destination", default="VCE")
    parser.add_argument("--config", default="", help="JSON config with per-period constraints")
    parser.add_argument("--min-nights", type=int, default=None)
    parser.add_argument("--max-nights", type=int, default=None)
    parser.add_argument("--saturday-in", dest="saturday_in", action="store_true", default=True)
    parser.add_argument("--no-saturday-in", dest="saturday_in", action="store_false")
    parser.add_argument("--airlines", default=None, help="Restrict to airlines (substring, comma-list)")
    parser.add_argument("--no-nonstop", dest="nonstop", action="store_false", default=None,
                        help="Also allow connecting flights")
    parser.add_argument("--earliest-departure", default=None, help="HARD: drop legs leaving before HH:MM")
    parser.add_argument("--preferred-departure", default=None, help="SOFT: legs before HH:MM incur a penalty")
    parser.add_argument("--early-departure-penalty", type=float, default=None,
                        help="euro per minute early vs preferred-departure")
    parser.add_argument("--preferred-nights", type=int, default=None, help="SOFT target stay length")
    parser.add_argument("--short-stay-penalty", type=float, default=None,
                        help="euro per night below preferred-nights")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--out", default="round_trips.json")
    args = parser.parse_args()

    with open(args.data) as fh:
        dataset = FlightDataset.from_dict(json.load(fh))

    origin, destination = args.origin.upper(), args.destination.upper()
    outbound = [f for f in dataset.flights if f.origin == origin and f.destination == destination]
    inbound = [f for f in dataset.flights if f.origin == destination and f.destination == origin]

    periods = load_periods(args)
    all_combos: dict[tuple[str, str], dict] = {}
    for index, period in enumerate(periods):
        print(f"Period #{index} (outbound {period['from'] or '...'} .. {period['to'] or '...'})")
        for c in build_combo_candidates(outbound, inbound, period, args.saturday_in):
            existing = all_combos.get((c["outbound"]["flight_id"], c["return"]["flight_id"]))
            if existing is None or c["score"] < existing["score"]:
                all_combos[(c["outbound"]["flight_id"], c["return"]["flight_id"])] = c

    combos = sorted(all_combos.values(),
                    key=lambda c: (c["score"], c["price"], -c["nights"], c["outbound"]["departure"]))

    weekend_top = group_by_weekend(combos, args.top_k) if args.saturday_in else []

    result = {
        "metadata": {
            "data_source": dataset.source,
            "origin": origin,
            "destination": destination,
            "periods": periods,
            "valid_round_trips_found": len(combos),
        },
        "overall_best": combos[:args.limit],
        "per_weekend_top": weekend_top,
    }

    with open(args.out, "w") as fh:
        json.dump(result, fh, indent=2)

    print(f"Valid round trips: {len(combos)}  (outbound {len(outbound)} legs, return {len(inbound)} legs)")
    print(f"Saved: {args.out}")
    print("-" * 110)
    print(f"Overall best by score ({len(result['overall_best'])})")
    for c in result["overall_best"]:
        print(f"  {describe(c)}")
    if weekend_top:
        print("-" * 110)
        print(f"Top {args.top_k} per Saturday night")
        for group in weekend_top:
            print(f"  Saturday night {group['saturday']}:")
            for c in group["combos"]:
                print(f"    {describe(c)}")


if __name__ == "__main__":
    main()