#!/usr/bin/env python3
"""
Mock fetcher - generates deterministic sample flight data.

Usage:
    from fetchers import MockFetcher
    
    fetcher = MockFetcher()
    dataset = fetcher.fetch("BRU", "VCE", ["2026-09-01", "2026-09-02"])
    fetcher.save(dataset, "mock_flights.json")
"""

import re

from flight_monitor.flight_model import Flight, FlightDataset

from .base import Fetcher


def parse_duration_min(value) -> int:
    """Parse a duration from the API into whole minutes.

    Accepts numbers (minutes), "1h 40m", "11h", "45m", or empty/None (-> 0).
    """
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
    if value:
        hours = re.search(r"(\d+)\s*h", str(value))
        mins = re.search(r"(\d+)\s*m", str(value))
        total = (int(hours.group(1)) * 60 if hours else 0) + (int(mins.group(1)) if mins else 0)
        return total
    return 0


class MockFetcher(Fetcher):
    """Generate mock flight data for testing without API calls."""

    def fetch(self, origin: str, destination: str, dates: list[str]) -> FlightDataset:
        """Generate mock flight data for the given origin, destination, and dates."""
        all_flights = generate_sample_data(origin.upper(), destination.upper(), dates)
        return FlightDataset(source="sample", currency="EUR", flights=all_flights)


def generate_sample_data(from_airport: str, to_airport: str, dates: list) -> list:
    """Generate sample flight data when API is not available."""
    flights = []

    templates = [
        {"airline": "Brussels Airlines", "dep": "06:50", "arr": "08:35", "stops": 0, "price": 89.0},
        {"airline": "Brussels Airlines", "dep": "09:25", "arr": "11:10", "stops": 0, "price": 99.0},
        {"airline": "Brussels Airlines", "dep": "12:15", "arr": "14:00", "stops": 0, "price": 109.0},
        {"airline": "Brussels Airlines", "dep": "15:40", "arr": "17:25", "stops": 0, "price": 119.0},
        {"airline": "Brussels Airlines", "dep": "18:30", "arr": "20:15", "stops": 0, "price": 129.0},
    ]

    for date in dates:
        for i, t in enumerate(templates):
            flights.append(Flight(
                flight_id=f"{from_airport.upper()}-{to_airport.upper()}-{date}-{i + 1:03d}",
                origin=from_airport.upper(),
                destination=to_airport.upper(),
                date=date,
                airline=t["airline"],
                departure=t["dep"],
                arrival=t["arr"],
                arrival_day_offset=0,
                duration_min=parse_duration_min("1h 45m"),
                stops=t["stops"],
                price=t["price"],
                currency="EUR",
                is_best=i == 0,
            ))

    return flights
