#!/usr/bin/env python3
"""
Generate a mock dataset of ONE-WAY flights between BRU and VCE (both
directions) so the price algorithm can be developed without spending limited
RapidAPI requests.

The output conforms to flight_model.FlightDataset and is written to
mock_flights_BRU_VCE.json. Generation is deterministic (fixed seed), so the
file is reproducible.

Usage:
    python generate_mock_flights.py
    python generate_mock_flights.py --dates 2026-09-20 --out mock_one_day.json
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timedelta

from flight_model import Flight, FlightDataset

# One-way leg templates, order-independent:
# (airline, departure, arrival, arrival_day_offset, duration_min, stops, base_price)
TEMPLATES = [
    # Brussels Airlines nonstop (~1h45m)
    ("Brussels Airlines", "06:30", "08:15", 0, 105, 0, 92),
    ("Brussels Airlines", "09:05", "10:50", 0, 105, 0, 99),
    ("Brussels Airlines", "12:20", "14:05", 0, 105, 0, 108),
    ("Brussels Airlines", "15:40", "17:25", 0, 105, 0, 119),
    ("Brussels Airlines", "18:10", "19:55", 0, 105, 0, 126),
    # 1-stop via hubs
    ("KLM", "08:40", "12:15", 0, 215, 1, 178),
    ("SWISS", "07:15", "11:05", 0, 230, 1, 214),
    ("Lufthansa", "11:30", "14:50", 0, 200, 1, 196),
    ("ITA", "14:10", "18:10", 0, 240, 1, 155),
    ("Air France", "16:50", "20:35", 0, 225, 1, 183),
    ("Austrian", "19:25", "23:35", 0, 250, 1, 205),
    ("Iberia", "17:30", "05:30", 1, 720, 1, 176),
    ("Vueling", "13:05", "23:05", 0, 600, 1, 148),
    ("Turkish Airlines", "20:40", "04:40", 1, 480, 1, 238),
    ("Vueling", "21:20", "08:20", 1, 660, 1, 132),
    # cheap 2-stop
    ("Vueling", "12:40", "05:10", 1, 990, 2, 138),
    ("Iberia", "15:50", "06:20", 1, 870, 2, 152),
]


def weekend_factor(day) -> float:
    if day.weekday() >= 5:  # Sat / Sun
        return 1.15
    if day.weekday() == 4:  # Fri
        return 1.05
    return 1.0


def parse_dates(arg: str):
    if ".." in arg:
        start_s, end_s = arg.split("..", 1)
        start = datetime.strptime(start_s.strip(), "%Y-%m-%d").date()
        end = datetime.strptime(end_s.strip(), "%Y-%m-%d").date()
        return [start + timedelta(days=i) for i in range((end - start).days + 1)]
    return [datetime.strptime(d.strip(), "%Y-%m-%d").date() for d in arg.split(",") if d.strip()]


def build(dates, origin: str, destination: str) -> FlightDataset:
    """Build mock one-way legs from origin to destination for every date."""
    rng = random.Random(2026)
    dataset = FlightDataset(source="mock", currency="EUR")

    for day in dates:
        day_str = day.isoformat()
        factor = weekend_factor(day)
        legs = []
        for airline, dep, arr, offset, dur, stops, base in TEMPLATES:
            price = round(base * factor * (1 + rng.uniform(-0.06, 0.10)), 2)
            legs.append((airline, dep, arr, offset, dur, stops, price))
        legs.sort(key=lambda t: t[1])  # chronological throughout the day

        best_price = min(p for *_ignored, p in legs)
        best_nonstop = min((p for *_, p in (t for t in legs if t[5] == 0)), default=None)

        for idx, (airline, dep, arr, offset, dur, stops, price) in enumerate(legs):
            is_best = price == best_price or (best_nonstop is not None and price == best_nonstop)
            dataset.add(Flight(
                flight_id=f"{origin}-{destination}-{day_str}-{idx + 1:03d}",
                origin=origin,
                destination=destination,
                date=day_str,
                airline=airline,
                departure=dep,
                arrival=arr,
                arrival_day_offset=offset,
                duration_min=dur,
                stops=stops,
                price=float(price),
                currency="EUR",
                is_best=is_best,
            ))
    return dataset


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate deterministic BRU <-> VCE mock flight data."
    )
    parser.add_argument(
        "--dates",
        default="2026-09-01..2027-01-31",
        help="Date range (start..end, e.g. 2026-09-01..2027-01-31) "
             "or comma-separated dates (YYYY-MM-DD)",
    )
    parser.add_argument("--out", default="mock_flights_BRU_VCE.json", help="Output JSON file")
    args = parser.parse_args()

    dates = parse_dates(args.dates)
    outbound = build(dates, "BRU", "VCE")
    inbound = build(dates, "VCE", "BRU")
    combined = FlightDataset(
        source="mock",
        currency="EUR",
        flights=outbound.flights + inbound.flights,
    )

    with open(args.out, "w") as fh:
        json.dump(combined.to_dict(), fh, indent=2)

    prices = [f.price for f in combined.flights]
    print(f"Saved {args.out}")
    print(f"  dates:      {dates[0]} .. {dates[-1]} ({len(dates)} days)")
    print(f"  flights:    {len(combined.flights)}")
    print(f"  directions: {sorted({(f.origin, f.destination) for f in combined.flights})}")
    print(f"  prices:     {min(prices):g} - {max(prices):g} EUR")


if __name__ == "__main__":
    main()