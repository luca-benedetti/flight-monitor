#!/usr/bin/env python3
"""
Build the single fares artifact served to the widget.

Scrapes only the dates that can actually form a valid round trip given the
config periods: outbound dates inside each period's [from, to], and return
dates = outbound date + min..max nights. By default only a nonstop pass is
scraped per direction (the widget only shows direct flights). With
--with-connections an extra pass for all offers is scraped and merged too
(Google's default list often omits direct flights, e.g. VCE->BRU). Legs are
deduped, flight ids renumbered, is_best recomputed, and the result validated.

Per-day results are cached in --cache-dir so a failed or interrupted run can
be resumed without re-fetching. Days that fail after retries are skipped and
the partial dataset is still published (the skipped days are listed); the run
only exits non-zero if nothing could be fetched.

Usage:
    python -m flight_monitor.build_fares                        # nonstop-only
    python -m flight_monitor.build_fares --with-connections     # + all offers
    python -m flight_monitor.build_fares --dates 2026-09-05,2026-09-08   # smoke
    python -m flight_monitor.build_fares --dry-run              # show dates only
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

from flight_monitor.flight_model import Flight, FlightDataset, validate

from .fetchers import ScraperFetcher

DEFAULT_MIN_NIGHTS = 1
DEFAULT_MAX_NIGHTS = 14


def load_periods(path: str) -> list[dict]:
    """Read a round-trip config file (list of periods or {'periods': [...]})."""
    with open(path) as fh:
        loaded = json.load(fh)
    raw = loaded.get("periods") or [loaded]
    periods = []
    for i, p in enumerate(raw):
        for key in ("from", "to"):
            if not p.get(key):
                raise ValueError(f"period #{i}: missing {key!r} date")
            try:
                date.fromisoformat(p[key])
            except ValueError:
                raise ValueError(f"period #{i}: {key} must be YYYY-MM-DD") from None
        periods.append(
            {
                **p,
                "min_nights": int(p.get("min_nights", DEFAULT_MIN_NIGHTS)),
                "max_nights": int(p.get("max_nights", DEFAULT_MAX_NIGHTS)),
            }
        )
    return periods


def scorable_dates(periods: list[dict]) -> tuple[list[str], list[str]]:
    """Return (outbound_dates, return_dates) that a round trip can use."""
    outbound: set[str] = set()
    returns: set[str] = set()
    for p in periods:
        day = date.fromisoformat(p["from"])
        to = date.fromisoformat(p["to"])
        while day <= to:
            outbound.add(day.isoformat())
            for nights in range(p["min_nights"], p["max_nights"] + 1):
                returns.add((day + timedelta(days=nights)).isoformat())
            day += timedelta(days=1)
    return sorted(outbound), sorted(returns)


def _leg_key(f: Flight) -> tuple:
    return (
        f.origin,
        f.destination,
        f.date,
        f.departure,
        f.arrival,
        f.airline.strip().lower(),
    )


def merge_passes(full: list[Flight], extra: list[Flight]) -> list[Flight]:
    """Merge two scrapes of the same direction, keeping cheapest per identical leg."""
    best: dict = {}
    for f in [*full, *extra]:
        key = _leg_key(f)
        if key not in best or f.price < best[key].price:
            best[key] = f

    ordered = sorted(best.values(), key=lambda f: (f.date, f.departure, f.price))
    for index, flight in enumerate(ordered, start=1):
        flight.flight_id = f"{flight.origin}-{flight.destination}-{flight.date}-{index:03d}"

    best_per_day: dict = defaultdict(list)
    for f in ordered:
        best_per_day[(f.origin, f.destination, f.date)].append(f)
    best_ids = {min(fl, key=lambda x: x.price).flight_id for fl in best_per_day.values()}
    for f in ordered:
        f.is_best = f.flight_id in best_ids
    return ordered


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the fares.json artifact")
    parser.add_argument("--config", default="config/round_trip_config.json")
    parser.add_argument("--out", default="data/fares.json")
    parser.add_argument(
        "--dates", default="",
        help="Comma-separated dates for BOTH directions (overrides config-derived scope)",
    )
    parser.add_argument(
        "--with-connections",
        action="store_true",
        help="Also scrape the all-connections pass and merge it (default: nonstop only)",
    )
    parser.add_argument(
        "--cache-dir",
        default="data/fares_cache",
        help="Directory for per-day results, reused to resume interrupted runs",
    )
    parser.add_argument(
        "--retries", type=int, default=2,
        help="Extra attempts per day after the first failure",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--delay", type=float, default=1.5, help="Pause between days")
    args = parser.parse_args()

    periods = load_periods(args.config)

    if args.dates:
        outbound = sorted({d.strip() for d in args.dates.split(",") if d.strip()})
        returns = list(outbound)
    else:
        outbound, returns = scorable_dates(periods)

    print(f"Scope:  outbound {len(outbound)} dates ({outbound[0]} .. {outbound[-1]})")
    print(f"        return  {len(returns)} dates ({returns[0]} .. {returns[-1]})")
    if args.dry_run:
        print("Dry run - nothing scraped.")
        return

    fetcher_kwargs = dict(
        headless=not args.headed,
        delay_sec=args.delay,
        cache_dir=args.cache_dir,
        retries=args.retries,
        allow_partial=True,
    )
    nonstop_fetcher = ScraperFetcher(max_stops=0, **fetcher_kwargs)
    if args.with_connections:
        connections_fetcher = ScraperFetcher(**fetcher_kwargs)
    directions = [
        ("BRU", "VCE", outbound),
        ("VCE", "BRU", returns),
    ]

    datasets = []
    skipped = []
    for origin, destination, dates in directions:
        print(f"\nPass {origin} -> {destination}")
        print("  nonstop only")
        nonstop = nonstop_fetcher.fetch(origin, destination, dates)
        skipped.extend(nonstop_fetcher.failed_days)
        extras = nonstop.flights

        if args.with_connections:
            print("  + all offers")
            full = connections_fetcher.fetch(origin, destination, dates)
            skipped.extend(connections_fetcher.failed_days)
            merged = merge_passes(full.flights, extras)
            print(
                f"Merged {origin}->{destination}: {len(full.flights)} full + "
                f"{len(extras)} nonstop -> {len(merged)} unique"
            )
        else:
            merged = merge_passes([], extras)
            print(
                f"Merged {origin}->{destination}: {len(extras)} nonstop -> "
                f"{len(merged)} unique"
            )
        datasets.append(merged)

    if skipped:
        print("\nSkipped days (partial data still published; re-run resumes from cache):")
        for day in skipped:
            print(f"  {day}")

    fares = FlightDataset(
        source="scraper_google_flights", currency="EUR",
        flights=[f for ds in datasets for f in ds],
    )
    errors = validate(fares.to_dict())
    if errors:
        print("Validation failed:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    payload = fares.to_dict()
    if skipped:
        payload["metadata"]["skipped_days"] = [s.split(": ", 1)[0] for s in skipped]
    with open(args.out, "w") as fh:
        json.dump(payload, fh, indent=2)

    prices = [f.price for f in fares.flights]
    print("-" * 60)
    print(f"Saved:   {args.out}")
    print(f"Flights: {len(fares.flights)} ({len({f.date for f in fares.flights})} dates)")
    print(
        f"Directions: {sorted({(f.origin, f.destination) for f in fares.flights})}"
    )
    print(f"Nonstop: {sum(1 for f in fares.flights if f.stops == 0)}")
    if prices:
        print(f"Price:   {min(prices):g} - {max(prices):g} EUR")


if __name__ == "__main__":
    main()
