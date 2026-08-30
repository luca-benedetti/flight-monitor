#!/usr/bin/env python3
"""
Scraper fetcher - pulls real Google Flights results via fast-flights, rendered
in a real headless browser to get past Google's EU consent wall.

Usage:
    from fetchers import ScraperFetcher

    fetcher = ScraperFetcher()
    dataset = fetcher.fetch("BRU", "VCE", ["2026-09-05", "2026-09-06"])
    fetcher.save(dataset, "scraped_flights.json")

Requires Google Chrome (or a Playwright Chromium build) installed locally.

Per-day results are cached to `cache_dir` and reused on re-runs, so an
interrupted or partially failed run can be resumed without re-fetching. Days
that fail after `retries` attempts are reported; with `allow_partial` the run
continues and only aborts if every day fails (e.g. blocked).
"""

import json
import os
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

from fast_flights import (
    FlightQuery,
    FlightsNotFound,
    Passengers,
    create_query,
)
from fast_flights.fetcher import URL as GOOGLE_FLIGHTS_URL
from fast_flights.parser import parse as parse_google_html
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from flight_monitor.flight_model import Flight, FlightDataset

from .base import Fetcher

CONSENT_TITLE = "Before you continue"
DS_SCRIPT_SELECTOR = "xpath=//script[contains(@class,'ds:1')]"


def _fmt_time(hm) -> str:
    return f"{hm[0]:02d}:{hm[1]:02d}"


def _day_offset(first_leg, last_leg) -> int:
    d = last_leg.arrival.date
    o = first_leg.departure.date
    return (date(*d) - date(*o)).days


class ScraperFetcher(Fetcher):
    """Fetch live flight offers by rendering Google Flights in a headless browser."""

    def __init__(
        self,
        airlines: list[str] | None = None,
        max_stops: int | None = None,
        earliest_departure_hour: int | None = None,
        latest_departure_hour: int | None = None,
        headless: bool = True,
        delay_sec: float = 2.0,
        timeout_ms: int = 45000,
        retries: int = 2,
        cache_dir: str | None = None,
        allow_partial: bool = False,
    ) -> None:
        self.airlines = airlines
        self.max_stops = max_stops
        self.earliest_departure_hour = earliest_departure_hour
        self.latest_departure_hour = latest_departure_hour
        self.headless = headless
        self.delay_sec = delay_sec
        self.timeout_ms = timeout_ms
        self.retries = retries
        self.cache_dir = cache_dir
        self.allow_partial = allow_partial
        self.failed_days: list[str] = []

    def fetch(self, origin: str, destination: str, dates: list[str]) -> FlightDataset:
        origin = origin.upper()
        destination = destination.upper()
        all_flights: list[Flight] = []
        self.failed_days = []
        total = len(dates)

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=self.headless, channel="chrome")
            except Exception:
                browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(locale="en-US")
            page = context.new_page()

            for index, day in enumerate(dates):
                cache_file = self._cache_file(origin, destination, day)
                cached = self._load_cached(cache_file)
                if cached is not None:
                    all_flights.extend(cached)
                    self._print_day(origin, destination, day, cached, cached=True)
                else:
                    mapped, exc = self._fetch_one(page, origin, destination, day)
                    if mapped is not None:
                        self._save_cache(cache_file, mapped)
                        all_flights.extend(mapped)
                        self._print_day(origin, destination, day, mapped)
                    else:
                        self.failed_days.append(
                            f"{day} ({origin}->{destination}): "
                            f"{type(exc).__name__}: {exc}"
                        )
                        print(f"  {day} ({origin}->{destination}): FAILED - {exc}")

                if index < total - 1 and self.delay_sec:
                    page.wait_for_timeout(int(self.delay_sec * 1000))

            browser.close()

        if self.failed_days and (not self.allow_partial or len(self.failed_days) == total):
            raise RuntimeError(
                f"{len(self.failed_days)}/{total} days failed:\n"
                + "\n".join(f"  {e}" for e in self.failed_days)
            )

        return FlightDataset(
            source="scraper_google_flights", currency="EUR", flights=all_flights
        )

    def _fetch_one(
        self, page, origin: str, destination: str, day: str
    ) -> tuple[list[Flight] | None, Exception | None]:
        """Fetch one day, retrying on transient errors (e.g. parser hiccups)."""
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                _, html = self._fetch_day_html(page, origin, destination, day)
                try:
                    offers = parse_google_html(html)
                except FlightsNotFound:
                    offers = []
                return self._to_flights(offers, origin, destination, day), None
            except Exception as exc:  # noqa: BLE001 - report per-day failure
                last_exc = exc
                if attempt < self.retries:
                    retry_delay = self.delay_sec * 2 if self.delay_sec else 4.0
                    print(
                        f"  {day}: attempt {attempt + 1} failed "
                        f"({type(exc).__name__}: {exc}); retrying"
                    )
                    page.wait_for_timeout(int(retry_delay * 1000))
        return None, last_exc

    def _stops_label(self) -> str:
        return "nonstop" if self.max_stops == 0 else "all"

    def _cache_file(self, origin: str, destination: str, day: str) -> Path:
        return (
            Path(self.cache_dir)
            / f"{origin}_{destination}_{self._stops_label()}"
            / f"{day}.json"
        )

    def _load_cached(self, cache_file: Path) -> list[Flight] | None:
        if not self.cache_dir or not cache_file.is_file():
            return None
        try:
            with open(cache_file) as fh:
                return [Flight.from_dict(f) for f in json.load(fh)]
        except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError):
            return None

    def _save_cache(self, cache_file: Path, flights: list[Flight]) -> None:
        if not self.cache_dir:
            return
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix(".json.tmp")
        with open(tmp, "w") as fh:
            json.dump([f.to_dict() for f in flights], fh)
        os.replace(tmp, cache_file)

    def _print_day(
        self,
        origin: str,
        destination: str,
        day: str,
        flights: list[Flight],
        cached: bool = False,
    ) -> None:
        n = len(flights)
        cheapest = min(flights, key=lambda f: f.price) if flights else None
        price_info = f"{cheapest.price:g} EUR" if cheapest else "-"
        tag = " (cached)" if cached else ""
        print(
            f"  {day} ({origin}->{destination}): {n} offers, "
            f"cheapest {price_info}{tag}"
        )

    def _fetch_day_html(
        self, page, origin: str, destination: str, day: str
    ) -> tuple[str, str]:
        query = create_query(
            flights=[
                FlightQuery(
                    date=day,
                    from_airport=origin,
                    to_airport=destination,
                    max_stops=self.max_stops,
                    airlines=self.airlines,
                    earliest_departure_hour=self.earliest_departure_hour,
                    latest_departure_hour=self.latest_departure_hour,
                )
            ],
            seat="economy",
            trip="one-way",
            passengers=Passengers(adults=1),
            language="en-US",
            currency="EUR",
        )
        page.goto(
            f"{GOOGLE_FLIGHTS_URL}?{urlencode(query.params())}",
            wait_until="domcontentloaded",
            timeout=self.timeout_ms,
        )
        self._bypass_consent(page)
        page.wait_for_selector(DS_SCRIPT_SELECTOR, state="attached", timeout=self.timeout_ms)
        # Give the "best" price row a beat to settle before snapshotting.
        page.wait_for_timeout(1200)
        return (GOOGLE_FLIGHTS_URL, page.content())

    def _bypass_consent(self, page) -> None:
        try:
            page.wait_for_selector(DS_SCRIPT_SELECTOR, state="attached", timeout=4000)
            return
        except PlaywrightTimeoutError:
            pass
        if CONSENT_TITLE not in page.title():
            return
        print("    (consent wall detected - accepting)")
        try:
            page.get_by_role("button", name=re.compile(r"accept", re.I)).first.click(
                timeout=8000
            )
        except Exception:
            page.locator("button:has-text('cept')").first.click(timeout=8000)
        page.wait_for_timeout(2000)

    def _to_flights(
        self, offers, origin: str, destination: str, day: str
    ) -> list[Flight]:
        name_map = {a.code: a.name for a in offers.metadata.airlines}
        mapped: list[Flight] = []
        for i, offer in enumerate(offers):
            legs = offer.flights
            first, last = legs[0], legs[-1]
            airlines = [
                (name_map.get(code) or code) for code in offer.airlines
            ]
            mapped.append(
                Flight(
                    flight_id=f"{origin}-{destination}-{day}-{i + 1:03d}",
                    origin=origin,
                    destination=destination,
                    date=day,
                    airline=" / ".join(airlines) or "unknown",
                    departure=_fmt_time(first.departure.time),
                    arrival=_fmt_time(last.arrival.time),
                    arrival_day_offset=_day_offset(first, last),
                    duration_min=sum(leg.duration for leg in legs),
                    stops=len(legs) - 1,
                    price=float(offer.price),
                    currency="EUR",
                    is_best=i == 0,
                )
            )
        return mapped
