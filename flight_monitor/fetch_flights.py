#!/usr/bin/env python3
"""
Fetch flights from any airport to any airport using RapidAPI (Google Flights).

Usage:
    export RAPIDAPI_KEY=your_key_here
    python fetch_flights.py --from BRU --to VCE --dates 2026-09-01

    # Filter server-side: nonstop only, and/or restrict to specific airlines
    # (preferred_airlines accepts IATA codes like SN or alliances like STAR_ALLIANCE):
    python fetch_flights.py --from BRU --to VCE --dates 2026-09-01 --max-stops 0 --airlines SN

    # Sample data only:
    python fetch_flights.py --from BRU --to VCE --sample

Get free API key at: https://rapidapi.com/Crawlio/api/google-flights8
"""

import json
import argparse
import os
import re
import requests
from datetime import datetime, timedelta, timezone


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

                        flights.append({
                            "flight_id": (
                                f"{from_airport.upper()}-{to_airport.upper()}-{date}-{i + 1:03d}"
                            ),
                            "origin": from_airport.upper(),
                            "destination": to_airport.upper(),
                            "date": date,
                            "airline": airline,
                            "departure": str(dep_time),
                            "arrival": str(arr_time),
                            "arrival_day_offset": arrival_day_offset,
                            "duration_min": duration_min,
                            "stops": stops,
                            "price": price,
                            "currency": "EUR",
                            "is_best": bool(flight.get("is_best", i == 0)),
                        })
                except Exception:
                    continue
            
            return flights
        else:
            print(f"  Error: {response.status_code}")
            return []
            
    except Exception as e:
        print(f"  Error: {type(e).__name__}")
        return []


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
            flights.append({
                "flight_id": f"{from_airport.upper()}-{to_airport.upper()}-{date}-{i + 1:03d}",
                "origin": from_airport.upper(),
                "destination": to_airport.upper(),
                "date": date,
                "airline": t["airline"],
                "departure": t["dep"],
                "arrival": t["arr"],
                "arrival_day_offset": 0,
                "duration_min": parse_duration_min("1h 45m"),
                "stops": t["stops"],
                "price": t["price"],
                "currency": "EUR",
                "is_best": i == 0,
            })

    return flights


def main():
    parser = argparse.ArgumentParser(description='Fetch flight data')
    parser.add_argument('--from', dest='from_airport', default='BRU', help='Origin airport (e.g., BRU)')
    parser.add_argument('--to', dest='to_airport', default='VCE', help='Destination airport (e.g., VCE)')
    parser.add_argument('--dates', default='', help='Comma-separated dates (YYYY-MM-DD)')
    parser.add_argument('--days', type=int, default=7, help='Days to search from today')
    parser.add_argument('--key', default='', help='RapidAPI key (or set RAPIDAPI_KEY env var)')
    parser.add_argument('--airlines', default='', help='Comma-separated IATA codes to restrict to (e.g. SN) or alliance (e.g. STAR_ALLIANCE)')
    parser.add_argument('--max-stops', type=int, default=None, help='Max stops: 0 = nonstop only, 1, 2 (default: no limit)')
    parser.add_argument('--sample', action='store_true', help='Use sample data only')
    
    args = parser.parse_args()
    
    # Get API key
    api_key = args.key or os.environ.get('RAPIDAPI_KEY', '')
    
    # Parse dates
    if args.dates:
        dates = [d.strip() for d in args.dates.split(',')]
    else:
        start_date = datetime.now() + timedelta(days=1)
        dates = [(start_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(args.days)]
    
    print(f"Route: {args.from_airport.upper()} → {args.to_airport.upper()}")
    print(f"Dates: {', '.join(dates)}")
    filters = []
    if args.max_stops is not None:
        filters.append(f"max_stops={args.max_stops}")
    if args.airlines:
        filters.append(f"airlines={args.airlines.upper()}")
    if filters:
        print(f"Filters: {', '.join(filters)} (applied server-side)")
    print("-" * 50)
    
    all_flights = []
    used_sample = False

    if args.sample or not api_key:
        used_sample = True
        if not api_key:
            print("⚠ No API key. Set RAPIDAPI_KEY env var or use --key")
            print("   Get free key: https://rapidapi.com/Crawlio/api/google-flights8")
            print("   Using sample data...")
        else:
            print("Using sample data (--sample flag)...")

        all_flights = generate_sample_data(args.from_airport, args.to_airport, dates)
    else:
        print(f"Using RapidAPI (Google Flights)...")
        for date in dates:
            print(f"Fetching {date}...", end=" ")
            flights = fetch_rapidapi_flights(
                args.from_airport, args.to_airport, date, api_key,
                max_stops=args.max_stops, airlines=args.airlines,
            )
            if flights:
                print(f"✓ {len(flights)} flights")
                all_flights.extend(flights)
            else:
                print("✗ no results")

        if not all_flights:
            used_sample = True
            print("\n⚠ No results from API. Using sample data...")
            all_flights = generate_sample_data(args.from_airport, args.to_airport, dates)

    # Save JSON (data model: see flight_model.py)
    output = {
        "metadata": {
            "schema_version": "1.0",
            "currency": "EUR",
            "source": "sample" if used_sample else "rapidapi_google_flights",
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "flights": all_flights
    }
    
    filename = f"flights_{args.from_airport.upper()}_{args.to_airport.upper()}.json"
    with open(filename, "w") as f:
        json.dump(output, f, indent=2)
    
    print("-" * 50)
    print(f"Saved: {filename}")
    print(f"Total flights: {len(all_flights)}")


if __name__ == "__main__":
    main()
