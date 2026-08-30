#!/usr/bin/env python3
"""
Fetchers package - different ways to obtain flight data.

Usage:
    from flight_monitor.fetchers import RapidAPIFetcher, MockFetcher

    # Fetch from API
    fetcher = RapidAPIFetcher(api_key="your-key")
    dataset = fetcher.fetch("BRU", "VCE", ["2026-09-01", "2026-09-02"])
    fetcher.save(dataset, "flights.json")

    # Use mock data
    fetcher = MockFetcher()
    dataset = fetcher.fetch("BRU", "VCE", ["2026-09-01", "2026-09-02"])
    fetcher.save(dataset, "mock_flights.json")
"""

from flight_monitor.flight_model import Flight, FlightDataset

from .base import Fetcher
from .mock import MockFetcher, generate_sample_data
from .rapid_api import RapidAPIFetcher, fetch_rapidapi_flights
from .scraper import ScraperFetcher

__all__ = [
    "Fetcher",
    "RapidAPIFetcher",
    "MockFetcher",
    "ScraperFetcher",
    "fetch_rapidapi_flights",
    "generate_sample_data",
    "FlightDataset",
    "Flight",
]
