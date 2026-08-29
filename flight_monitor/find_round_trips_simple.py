#!/usr/bin/env python3
"""
Simplified round-trip finder.

A simple interface to find the best round-trip flights using:
1. Mock data (fetch)
2. Filter based on constraints
3. Find best pairs (algorithm)
4. Return top 3

Usage:
    from find_round_trips_simple import find_best_round_trips
    
    results = find_best_round_trips(
        origin="BRU",
        destination="VCE", 
        dates=["2026-09-01", "2026-09-02", "2026-09-03"],
        min_nights=4,
        max_nights=12,
        nonstop_only=True,
        max_results=3
    )
    
    for trip in results:
        print(f"Price: €{trip['price']}, Score: {trip['score']}")
"""

from datetime import date, timedelta
from collections import defaultdict

from flight_monitor.flight_model import Flight, FlightDataset
from flight_monitor.fetchers import MockFetcher


def find_best_round_trips(
    origin: str,
    destination: str,
    dates: list[str],
    min_nights: int = 4,
    max_nights: int = 12,
    nonstop_only: bool = True,
    max_results: int = 3
) -> list[dict]:
    """
    Find the best round-trip flights.
    
    Args:
        origin: Origin airport code (e.g., "BRU")
        destination: Destination airport code (e.g., "VCE")
        dates: List of dates to search (e.g., ["2026-09-01", "2026-09-02"])
        min_nights: Minimum stay length
        max_nights: Maximum stay length
        nonstop_only: If True, only include nonstop flights
        max_results: Maximum number of results to return
    
    Returns:
        List of round-trip dictionaries, each containing:
        - outbound: outbound flight details
        - return: return flight details  
        - outbound_date: outbound date
        - return_date: return date
        - nights: number of nights
        - price: total price
        - score: calculated score (price + penalties)
    """
    
    # Step 1: Fetch data (using mock for now)
    fetcher = MockFetcher()
    dataset = fetcher.fetch(origin, destination, dates)
    
    # Also fetch reverse direction for return flights
    return_dataset = fetcher.fetch(destination, origin, dates)
    
    # Combine flights
    all_flights = dataset.flights + return_dataset.flights
    
    # Step 2: Filter data - separate outbound and return flights
    outbound = [f for f in all_flights if f.origin == origin.upper() and f.destination == destination.upper()]
    inbound = [f for f in all_flights if f.origin == destination.upper() and f.destination == origin.upper()]
    
    # Apply hard filters
    if nonstop_only:
        outbound = [f for f in outbound if f.stops == 0]
        inbound = [f for f in inbound if f.stops == 0]
    
    # Step 3: Find best pairs (algorithm)
    combos = []
    
    # Group outbound flights by date
    out_by_date: dict[str, list[Flight]] = defaultdict(list)
    for f in outbound:
        out_by_date[f.date].append(f)
    
    # Group return flights by date  
    ret_by_date: dict[str, list[Flight]] = defaultdict(list)
    for f in inbound:
        ret_by_date[f.date].append(f)
    
    # Pair outbound with return flights
    for out_date_str, out_flights in out_by_date.items():
        out_date = date.fromisoformat(out_date_str)
        
        for nights in range(min_nights, max_nights + 1):
            ret_date = out_date + timedelta(days=nights)
            ret_flights = ret_by_date.get(ret_date.isoformat(), [])
            
            if not ret_flights:
                continue
            
            for of in out_flights:
                for rf in ret_flights:
                    # Calculate score (just price for now - no penalties in simple version)
                    total_price = of.price + rf.price
                    combos.append({
                        "outbound": of.to_dict(),
                        "return": rf.to_dict(),
                        "outbound_date": of.date,
                        "return_date": rf.date,
                        "nights": nights,
                        "price": total_price,
                        "score": total_price,  # Score = price for simple version
                    })
    
    # Step 4: Sort by score and return top N
    combos.sort(key=lambda c: (c["score"], c["price"], -c["nights"]))
    
    return combos[:max_results]


def main():
    """Demo the simple round-trip finder."""
    print("Finding best round trips...")
    print("=" * 50)
    
    # Find best round trips for a few dates in September 2026
    results = find_best_round_trips(
        origin="BRU",
        destination="VCE",
        dates=["2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18", "2026-09-19"],
        min_nights=4,
        max_nights=12,
        nonstop_only=True,
        max_results=3
    )
    
    print(f"\nFound {len(results)} best round trips:\n")
    
    for i, trip in enumerate(results, 1):
        print(f"#{i}:")
        print(f"  Outbound: {trip['outbound_date']} {trip['outbound']['departure']}-{trip['outbound']['arrival']} ({trip['outbound']['airline']})")
        print(f"  Return:   {trip['return_date']} {trip['return']['departure']}-{trip['return']['arrival']} ({trip['return']['airline']})")
        print(f"  Nights: {trip['nights']}")
        print(f"  Price: €{trip['price']:.2f}")
        print(f"  Score: {trip['score']:.2f}")
        print()


if __name__ == "__main__":
    main()
