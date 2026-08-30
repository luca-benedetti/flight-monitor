#!/usr/bin/env python3
"""
Data model for the one-way flight data produced and consumed by the BRU <-> VCE
flight price tool.

Canonical JSON shape
--------------------
{
  "metadata": {
    "schema_version": "1.0",
    "currency": "EUR",
    "source": "mock | sample | rapidapi_google_flights",
    "generated_at": "2026-08-29T12:00:00Z"
  },
  "flights": [
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
  ]
}

Every record is a ONE-WAY flight offer. A round trip is built at the algorithm
level by pairing a BRU -> VCE leg with a VCE -> BRU leg on compatible dates, so
a single dataset normally contains both directions.

Conventions:
  * departure/arrival are local times "HH:MM" (24h).
  * arrival_day_offset is 0 when arrival lands the same calendar day as
    departure, 1 when it lands the next day (red-eyes).
  * duration_min is the total door-to-door trip duration in minutes.
  * price is a number in `currency` (never a string) so it can be compared
    without parsing.

Validation:
    python flight_model.py flights_BRU_VCE.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
IATA_RE = re.compile(r"^[A-Z]{3}$")

SOURCES = ("mock", "sample", "rapidapi_google_flights", "scraper_google_flights")
SCHEMA_VERSION = "1.0"


def _norm_iata(code, name):
    code = str(code).strip().upper()
    if not IATA_RE.match(code):
        raise ValueError(f"{name} must be a 3-letter IATA code, got {code!r}")
    return code


@dataclass
class Flight:
    """A single one-way flight offer."""

    flight_id: str
    origin: str
    destination: str
    date: str
    airline: str
    departure: str
    arrival: str
    arrival_day_offset: int = 0
    duration_min: int = 0
    stops: int = 0
    price: float = 0.0
    currency: str = "EUR"
    is_best: bool = False

    def __post_init__(self) -> None:
        self.origin = _norm_iata(self.origin, "origin")
        self.destination = _norm_iata(self.destination, "destination")
        self.currency = str(self.currency).strip().upper()
        if not self.flight_id:
            raise ValueError("flight_id must not be empty")
        if not self.airline:
            raise ValueError("airline must not be empty")
        if self.origin == self.destination:
            raise ValueError("origin and destination must differ")
        if not DATE_RE.match(self.date):
            raise ValueError(f"date must be YYYY-MM-DD, got {self.date!r}")
        try:
            datetime.strptime(self.date, "%Y-%m-%d")
        except ValueError:
            raise ValueError(
                f"date is not a valid calendar day, got {self.date!r}"
            ) from None
        if not TIME_RE.match(self.departure):
            raise ValueError(f"departure must be HH:MM, got {self.departure!r}")
        if not TIME_RE.match(self.arrival):
            raise ValueError(f"arrival must be HH:MM, got {self.arrival!r}")
        if not isinstance(self.arrival_day_offset, int) or self.arrival_day_offset < 0:
            raise ValueError(
                f"arrival_day_offset must be an int >= 0, got {self.arrival_day_offset!r}"
            )
        if not isinstance(self.duration_min, int) or self.duration_min < 0:
            raise ValueError(f"duration_min must be an int >= 0, got {self.duration_min!r}")
        if not isinstance(self.stops, int) or self.stops < 0:
            raise ValueError(f"stops must be an int >= 0, got {self.stops!r}")
        if not isinstance(self.price, (int, float)) or self.price < 0:
            raise ValueError(f"price must be a non-negative number, got {self.price!r}")
        if not IATA_RE.match(self.currency):
            raise ValueError(f"currency must be an ISO 4217 code, got {self.currency!r}")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Flight:
        return cls(**data)

    def __repr__(self) -> str:
        return (
            f"Flight({self.flight_id}, {self.origin}->{self.destination}, "
            f"{self.date} {self.departure}-{self.arrival}{'+' if self.arrival_day_offset else ''}, "
            f"{self.price:g} {self.currency})"
        )


@dataclass
class FlightDataset:
    """A dataset of one-way flight offers plus its metadata."""

    schema_version: str = SCHEMA_VERSION
    currency: str = "EUR"
    source: str = "mock"
    generated_at: str = ""
    flights: list[Flight] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.source not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}, got {self.source!r}")
        if not self.generated_at:
            self.generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.flights = [
            f if isinstance(f, Flight) else Flight.from_dict(f)
            for f in (self.flights or [])
        ]

    def add(self, flight: Flight) -> None:
        self.flights.append(flight)

    def to_dict(self) -> dict:
        return {
            "metadata": {
                "schema_version": self.schema_version,
                "currency": self.currency.strip().upper(),
                "source": self.source,
                "generated_at": self.generated_at,
            },
            "flights": [f.to_dict() for f in self.flights],
        }

    @classmethod
    def from_dict(cls, data: dict) -> FlightDataset:
        md = data.get("metadata", {})
        return cls(
            schema_version=md.get("schema_version", SCHEMA_VERSION),
            currency=md.get("currency", "EUR"),
            source=md.get("source", "mock"),
            generated_at=md.get("generated_at", ""),
            flights=[Flight.from_dict(f) for f in data.get("flights", [])],
        )


def validate(data: dict) -> list[str]:
    """Return a list of problems found (empty list means the dataset is valid)."""
    try:
        dataset = FlightDataset.from_dict(data)
    except (TypeError, KeyError, ValueError) as exc:
        return [f"invalid dataset: {exc}"]

    errors: list[str] = []
    seen_ids: set[str] = set()
    for i, flight in enumerate(dataset.flights):
        if flight.flight_id in seen_ids:
            errors.append(f"flights[{i}] duplicate flight_id {flight.flight_id!r}")
        seen_ids.add(flight.flight_id)
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a flight dataset JSON file against the data model."
    )
    parser.add_argument("file", help="JSON dataset produced by the model")
    args = parser.parse_args()

    try:
        with open(args.file) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read {args.file}: {exc}")
        sys.exit(2)

    errors = validate(data)
    if errors:
        print(f"{args.file}: INVALID")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    ds = FlightDataset.from_dict(data)
    prices = [f.price for f in ds.flights]
    print(f"{args.file}: OK")
    print(f"  schema_version: {ds.schema_version}  source: {ds.source}  currency: {ds.currency}")
    print(f"  flights:   {len(ds.flights)} ({len({f.date for f in ds.flights})} dates)")
    print(f"  directions: {sorted({(f.origin, f.destination) for f in ds.flights})}")
    print(f"  nonstop:   {sum(1 for f in ds.flights if f.stops == 0)}")
    print(f"  price:     {min(prices):g} - {max(prices):g} {ds.currency}")


if __name__ == "__main__":
    main()
