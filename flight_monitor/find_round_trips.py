#!/usr/bin/env python3
"""
Enumerate and rank round-trip combinations from a flight dataset (mock or
fetched) without spending any API requests.

Mirror of the widget/rank engine (web/filter.js + Scriptable widget): the
semantics here must match `computeTrips` exactly. Options are flat knobs:

  HARD filters:
    --nonstop-only / --airlines            every leg
    --earliest-departure HH:MM             every leg
    --dep-weekdays 1,4                     OUTBOUND only (0=Sun..6=Sat)
    --dep-after-hour 17                    OUTBOUND only
    --search-from / --search-to            OUTBOUND window ("" = open)
    --force-include-day YYYY-MM-DD         trip must cover this day
    --saturday-in                          require a Saturday night
    --min-nights / --max-nights            trip length range

  Ranking: price only (cheapest first; longer trips and earlier departures
  break ties).

Usage:
    find-round-trips --data fares.json --min-nights 4 --max-nights 10
    find-round-trips --data fares.json --dep-weekdays 1,4 --dep-after-hour 17
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import date, timedelta

from flight_monitor.flight_model import Flight, FlightDataset

TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ARGS = None


def to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def js_weekday_to_python(js_day: int) -> int:
    """Convert 0=Sun..6=Sat (widget) to python weekday() 0=Mon..6=Sun."""
    return (js_day + 6) % 7


def leg_ok(flight: Flight, opts) -> bool:
    if opts.nonstop and flight.stops > 0:
        return False
    airlines = [a.strip().lower() for a in (opts.airlines or "").split(",") if a.strip()]
    if airlines and not any(a in flight.airline.lower() for a in airlines):
        return False
    if opts.earliest_departure and to_minutes(flight.departure) < to_minutes(opts.earliest_departure):
        return False
    return True


def out_leg_ok(flight: Flight, opts) -> bool:
    if not leg_ok(flight, opts):
        return False
    if opts.dep_weekdays and date.fromisoformat(flight.date).weekday() not in {
        js_weekday_to_python(d) for d in opts.dep_weekdays
    }:
        return False
    if opts.dep_after_hour and to_minutes(flight.departure) < opts.dep_after_hour * 60:
        return False
    if opts.search_from and flight.date < opts.search_from:
        return False
    if opts.search_to and flight.date > opts.search_to:
        return False
    return True


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


def build_combo(of: Flight, rf: Flight, nights: int, saturday: date | None, price: float) -> dict:
    return {
        "outbound": of.to_dict(),
        "return": rf.to_dict(),
        "outbound_date": of.date,
        "return_date": rf.date,
        "nights": nights,
        "saturday_in": saturday.isoformat() if saturday else None,
        "price": price,
        "score": price,
    }


def sort_key(combo: dict):
    o, r = combo["outbound"], combo["return"]
    return (
        combo["score"], -combo["nights"], o["departure"], r["departure"],
        combo["outbound_date"], combo["return_date"],
    )


def compute(outbound: list[Flight], inbound: list[Flight], /) -> list[dict]:
    """Build and rank all combos from the legs. Mirrors Filter.computeTrips."""
    out_by_date: dict[str, list[Flight]] = defaultdict(list)
    ret_by_date: dict[str, list[Flight]] = defaultdict(list)
    for f in outbound:
        if out_leg_ok(f, ARGS):
            out_by_date[f.date].append(f)
    for f in inbound:
        if leg_ok(f, ARGS):
            ret_by_date[f.date].append(f)

    combos: list[dict] = []
    for out_date_str, out_flights in out_by_date.items():
        out_date = date.fromisoformat(out_date_str)
        for nights in range(ARGS.min_nights, ARGS.max_nights + 1):
            ret_str = (out_date + timedelta(days=nights)).isoformat()
            if ARGS.force_include_day and not (out_date_str <= ARGS.force_include_day <= ret_str):
                continue
            ret_flights = ret_by_date.get(ret_str, [])
            if not ret_flights:
                continue
            ret_date = date.fromisoformat(ret_str)
            if ARGS.saturday_in and not has_saturday_night(out_date, ret_date):
                continue
            saturday = first_saturday(out_date, ret_date) if ARGS.saturday_in else None
            for of in out_flights:
                for rf in ret_flights:
                    price = round(of.price + rf.price, 2)
                    combos.append(build_combo(of, rf, nights, saturday, price))

    combos.sort(key=sort_key)
    return combos


def describe(combo: dict) -> str:
    o, r = combo["outbound"], combo["return"]
    return (
        f"out {combo['outbound_date']} {o['departure']}-{o['arrival']} "
        f"| return {combo['return_date']} {r['departure']}-{r['arrival']} | "
        f"{combo['nights']}n | {combo['price']:.2f} €"
    )


def group_by_weekend(combos: list[dict], top_k: int) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for c in combos:
        groups[c["saturday_in"]].append(c)
    return [
        {"saturday": saturday, "combos": groups[saturday][:top_k]}
        for saturday in sorted(groups)
    ]


def main() -> None:
    global ARGS
    parser = argparse.ArgumentParser(
        description="Enumerate round trips locally with flat hard filters (matches the widget)."
    )
    parser.add_argument("--data", default="data/fares.json", help="Input dataset JSON")
    parser.add_argument("--origin", default="BRU")
    parser.add_argument("--destination", default="VCE")
    parser.add_argument("--min-nights", type=int, default=4)
    parser.add_argument("--max-nights", type=int, default=10)
    parser.add_argument("--saturday-in", dest="saturday_in", action="store_true")
    parser.add_argument("--no-saturday-in", dest="saturday_in", action="store_false")
    parser.set_defaults(saturday_in=True)
    parser.add_argument("--nonstop", dest="nonstop", action="store_true")
    parser.add_argument("--no-nonstop", dest="nonstop", action="store_false")
    parser.set_defaults(nonstop=True)
    parser.add_argument("--airlines", default="", help="Restrict to airlines (substring, comma-list)")
    parser.add_argument("--earliest-departure", default="", help="HARD: drop legs leaving before HH:MM")
    parser.add_argument("--dep-weekdays", default="",
                        help="OUTBOUND only: comma list of weekdays 0=Sun..6=Sat, e.g. 1,4")
    parser.add_argument("--dep-after-hour", type=int, default=0,
                        help="OUTBOUND only: depart at/after this hour (24h)")
    parser.add_argument("--search-from", default="", help="OUTBOUND window start (YYYY-MM-DD)")
    parser.add_argument("--search-to", default="", help="OUTBOUND window end (YYYY-MM-DD)")
    parser.add_argument("--force-include-day", default="", help="Trip must cover this day (YYYY-MM-DD)")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--out", default="round_trips.json")
    args = parser.parse_args()

    if args.min_nights < 0 or args.max_nights < args.min_nights:
        parser.error("--min-nights/--max-nights invalid")
    if args.earliest_departure and not TIME_RE.match(args.earliest_departure):
        parser.error("--earliest-departure must be HH:MM")
    for key in ("search_from", "search_to", "force_include_day"):
        value = getattr(args, key)
        if value and not DATE_RE.match(value):
            parser.error(f"--{key.replace('_', '-')} must be YYYY-MM-DD")
    try:
        args.dep_weekdays = [int(d) for d in (args.dep_weekdays or "").split(",") if d.strip()]
        if any(d < 0 or d > 6 for d in args.dep_weekdays):
            raise ValueError
    except ValueError:
        parser.error("--dep-weekdays must be 0..6 (0=Sun..6=Sat)")
    ARGS = args

    with open(args.data) as fh:
        dataset = FlightDataset.from_dict(json.load(fh))

    origin, destination = args.origin.upper(), args.destination.upper()
    outbound = [f for f in dataset.flights if f.origin == origin and f.destination == destination]
    inbound = [f for f in dataset.flights if f.origin == destination and f.destination == origin]

    combos = compute(outbound, inbound)
    weekend_top = group_by_weekend(combos, args.top_k) if args.saturday_in else []

    result = {
        "metadata": {
            "data_source": dataset.source,
            "origin": origin,
            "destination": destination,
            "options": {
                "min_nights": args.min_nights,
                "max_nights": args.max_nights,
                "saturday_in": args.saturday_in,
                "nonstop": args.nonstop,
                "airlines": args.airlines,
                "earliest_departure": args.earliest_departure,
                "dep_weekdays": args.dep_weekdays,
                "dep_after_hour": args.dep_after_hour,
                "search_from": args.search_from,
                "search_to": args.search_to,
                "force_include_day": args.force_include_day,
            },
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
    print(f"Overall best ({len(result['overall_best'])})")
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