#!/usr/bin/env python3
"""
RapidAPI (Google Flights) fetcher.

Usage:
    from fetchers import RapidAPIFetcher
    
    fetcher = RapidAPIFetcher(api_key="your-rapidapi-key")
    dataset = fetcher.fetch("BRU", "VCE", ["2026-09-01", "2026-09-02"])
    fetcher.save(dataset, "flights.json")
"""

import os
import re
from datetime import datetime

import requests

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


class RapidAPIFetcher(Fetcher):
    """Fetch flight data from RapidAPI (Google Flights) API."""

    def __init__(self, api_key: str = None, max_stops: int = None, airlines: str = ""):
        """
        Initialize the RapidAPI fetcher.
        
        Args:
            api_key: RapidAPI key (or set RAPIDAPI_KEY env var)
            max_stops: Maximum number of stops (0 = nonstop only)
            airlines: Comma-separated IATA codes to restrict to (e.g. "SN")
        """
        self.api_key = api_key or os.environ.get("RAPIDAPI_KEY", "")
        self.max_stops = max_stops
        self.airlines = airlines

    def fetch(self, origin: str, destination: str, dates: list[str]) -> FlightDataset:
        """Fetch flight data for the given origin, destination, and dates."""
        dataset = FlightDataset(source="rapidapi_google_flights", currency="EUR")

        for date in dates:
            flights = fetch_rapidapi_flights(
                origin, destination, date, self.api_key,
                max_stops=self.max_stops, airlines=self.airlines
            )
            for f in flights:
                dataset.add(f)

        return dataset


def fetch_rapidapi_flights(from_airport: str, to_airport: str, date: str, api_key: str,
                           max_stops=None, airlines: str = "") -> list:
    """Fetch flights using RapidAPI Google Flights API."""
    url = "https://google-flights8.p.rapidapi.com/api/v1/search"
    
    querystring = {
        "origin": from_airport.upper(),
        "destination": to_airport.upper(),
        "date": date,
        "adults": "1",
        "seat_class": "economy",
        "currency": "EUR",
    }

    # Server-side filtering: only hit the API once with the filters applied.
    if max_stops is not None:
        querystring["max_stops"] = str(max_stops)
    if airlines:
        querystring["preferred_airlines"] = ",".join(
            a.strip().upper() for a in airlines.split(",") if a.strip()
        )
    
    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "google-flights8.p.rapidapi.com"
    }
    
    try:
        response = requests.get(url, headers=headers, params=querystring, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            flights = []
            
            # Parse the response - structure depends on API version
            flight_lists = data.get("flights", []) or data.get("results", [])
            
            for i, flight in enumerate(flight_lists[:10]):  # Limit to 10
                try:
                    if isinstance(flight, dict):
                        price = flight.get("price", flight.get("total_price", 0))
                        airline = flight.get("airline", flight.get("airlines", flight.get("name", ["Unknown"])))
                        if isinstance(airline, list):
                            airline = airline[0] if airline else "Unknown"

                        # Times: google-flights8 uses top-level "departure"/"arrival" and
                        # per-segment "departure"/"arrival". Older schemes fall back below.
                        dep_time = ""
                        arr_time = ""

                        segments = flight.get("segments", []) or []
                        if isinstance(segments, list) and len(segments) > 0:
                            first_seg = segments[0]
                            last_seg = segments[-1]
                            dep_time = first_seg.get("departure", first_seg.get("dep_time", ""))
                            arr_time = last_seg.get("arrival", last_seg.get("arr_time", ""))

                        if not dep_time:
                            dep_time = flight.get("departure", flight.get("departure_time", flight.get("dep_time", "")))
                        if not arr_time:
                            arr_time = flight.get("arrival", flight.get("arrival_time", flight.get("arr_time", "")))

                        def to_hhmm(value):
                            if isinstance(value, str):
                                if "T" in value:
                                    return value.split("T")[-1][:5]
                                return value[:5]
                            return str(value)

                        dep_time = to_hhmm(dep_time) if dep_time else ""
                        arr_time = to_hhmm(arr_time) if arr_time else ""

                        arrival_day_offset = 0
                        if isinstance(segments, list) and len(segments) > 0:
                            try:
                                dep_dt = datetime.strptime(
                                    first_seg.get("departure", ""), "%Y-%m-%dT%H:%M")
                                arr_dt = datetime.strptime(
                                    last_seg.get("arrival", ""), "%Y-%m-%dT%H:%M")
                                arrival_day_offset = max(0, (arr_dt - dep_dt).days)
                            except ValueError:
                                arrival_day_offset = 0

                        duration_str = flight.get("duration", flight.get("fly_duration", ""))
                        duration_min = parse_duration_min(flight.get("duration_min", duration_str))
                        stops = flight.get("stops", flight.get("transitions", 0))

                        # Handle stops format (could be "Nonstop", "1 stop", or number)
                        if isinstance(stops, str):
                            if "Nonstop" in stops:
                                stops = 0
                            elif "stop" in stops:
                                try:
                                    stops = int(stops.split()[0])
                                except Exception:
                                    stops = 1

                        try:
                            price = float(flight.get("price", flight.get("total_price", 0)))
                        except (TypeError, ValueError):
                            price = 0.0

                        flights.append(Flight(
                            flight_id=f"{from_airport.upper()}-{to_airport.upper()}-{date}-{i + 1:03d}",
                            origin=from_airport.upper(),
                            destination=to_airport.upper(),
                            date=date,
                            airline=airline,
                            departure=str(dep_time),
                            arrival=str(arr_time),
                            arrival_day_offset=arrival_day_offset,
                            duration_min=duration_min,
                            stops=stops,
                            price=price,
                            currency="EUR",
                            is_best=bool(flight.get("is_best", i == 0)),
                        ))
                except Exception:
                    continue
            
            return flights
        else:
            print(f"  Error: {response.status_code}")
            return []
            
    except Exception as e:
        print(f"  Error: {type(e).__name__}")
        return []
