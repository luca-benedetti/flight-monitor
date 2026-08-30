#!/usr/bin/env python3
"""
Fetch flights by scraping Google Flights through a headless browser.

No API key and no mock fallback: every day must return real results or the run
fails with a report.

Usage:
    uv run python -m flight_monitor.scrape_flights --from BRU --to VCE --days 10
    uv run python -m flight_monitor.scrape_flights --from BRU --to VCE --dates 2026-09-05

    # Filter server-side during scrape:
    uv run python -m flight_monitor.scrape_flights --from BRU --to VCE \
        --days 10 --max-stops 0 --airlines SN \
        --earliest-departure-hour 6 --latest-departure-hour 20

Requires Google Chrome installed (used headless).
"""

import argparse
import sys
from datetime import datetime, timedelta

from flight_monitor.flight_model import validate

from .fetchers import ScraperFetcher
from .fetchers.scraper import GOOGLE_FLIGHTS_URL


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Google Flights for flight data")
    parser.add_argument("--from", dest="from_airport", default="BRU", help="Origin airport (e.g. BRU)")
    parser.add_argument("--to", dest="to_airport", default="VCE", help="Destination airport (e.g. VCE)")
    parser.add_argument("--dates", default="", help="Comma-separated dates (YYYY-MM-DD)")
    parser.add_argument("--days", type=int, default=10, help="How many consecutive days from start")
    parser.add_argument("--start", default="", help="First date (YYYY-MM-DD). Default: tomorrow")
    parser.add_argument("--airlines", default="", help="Comma-separated IATA codes to restrict to (e.g. SN)")
    parser.add_argument("--max-stops", type=int, default=None, help="Max stops: 0 = nonstop only, 1, 2")
    parser.add_argument("--earliest-departure-hour", type=int, default=None, help="Earliest departure hour (e.g. 6)")
    parser.add_argument("--latest-departure-hour", type=int, default=None, help="Latest departure hour (e.g. 20)")
    parser.add_argument("--out", default="", help="Output JSON path (default: data/scraped_flights_<FROM>_<TO>.json)")
    parser.add_argument("--delay", type=float, default=2.0, help="Pause between days in seconds")
    parser.add_argument("--headed", action="store_true", help="Show the browser window (debug)")
    args = parser.parse_args()

    origin = args.from_airport.upper()
    destination = args.to_airport.upper()

    if args.dates:
        dates = [d.strip() for d in args.dates.split(",") if d.strip()]
    else:
        start = args.start or (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        try:
            start_dt = datetime.strptime(start, "%Y-%m-%d")
        except ValueError:
            print(f"Invalid --start date {start!r} (expected YYYY-MM-DD)")
            sys.exit(2)
        dates = [(start_dt + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(args.days)]

    airlines = [a.strip().upper() for a in args.airlines.split(",") if a.strip()] or None

    print(f"Route:  {origin} -> {destination}")
    print(f"Dates:  {len(dates)} days ({dates[0]} .. {dates[-1]})")
    print(f"Source: live scrape of {GOOGLE_FLIGHTS_URL}")
    filters = []
    if args.max_stops is not None:
        filters.append(f"max_stops={args.max_stops}")
    if airlines:
        filters.append(f"airlines={','.join(airlines)}")
    if args.earliest_departure_hour is not None:
        filters.append(f"earliest_departure_hour={args.earliest_departure_hour}")
    if args.latest_departure_hour is not None:
        filters.append(f"latest_departure_hour={args.latest_departure_hour}")
    if filters:
        print(f"Filters: {', '.join(filters)}")
    print("-" * 50)

    fetcher = ScraperFetcher(
        airlines=airlines,
        max_stops=args.max_stops,
        earliest_departure_hour=args.earliest_departure_hour,
        latest_departure_hour=args.latest_departure_hour,
        headless=not args.headed,
        delay_sec=args.delay,
    )

    dataset = fetcher.fetch(origin, destination, dates)
    errors = validate(dataset.to_dict())
    if errors:
        print("Dataset invalid:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    out = (
        args.out
        or f"data/scraped_flights_{origin}_{destination}.json"
    )
    fetcher.save(dataset, out)

    prices = [f.price for f in dataset.flights]
    print("-" * 50)
    print(f"Saved:   {out}")
    print(f"Flights: {len(dataset.flights)} ({len({f.date for f in dataset.flights})} dates)")
    if prices:
        cheapest = min(dataset.flights, key=lambda f: f.price)
        print(
            f"Cheapest: {cheapest.price:g} EUR {cheapest.date} "
            f"{cheapest.departure}-{cheapest.arrival} {cheapest.airline}"
        )
        print(f"Price range: {min(prices):g} - {max(prices):g} EUR")


if __name__ == "__main__":
    main()
