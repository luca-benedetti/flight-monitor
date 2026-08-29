#!/usr/bin/env python3
"""
Base Fetcher class for flight data fetchers.
"""

import json

from flight_monitor.flight_model import FlightDataset


class Fetcher:
    """Base class for flight data fetchers."""
    
    def fetch(self, origin: str, destination: str, dates: list[str]) -> FlightDataset:
        """Fetch flight data for the given origin, destination, and dates."""
        raise NotImplementedError("Subclasses must implement fetch()")
    
    def save(self, dataset: FlightDataset, filename: str) -> None:
        """Save the dataset to a JSON file."""
        with open(filename, "w") as f:
            json.dump(dataset.to_dict(), f, indent=2)
