# from fast_flights import FlightQuery, Passengers, create_query, get_flights
#
# flight = FlightQuery(
#     date="2026-09-18",
#     from_airport="BRU",
#     to_airport="VCE",
#     airlines=["SN"],              # Brussels Airlines' IATA code
#     earliest_departure_hour=6,
#     latest_departure_hour=20,
# )
# query = create_query(flights=[flight], trip="one-way", passengers=Passengers(adults=1))
# res = get_flights(query)

import asyncio
from fast_flights import FlightData, Passengers, get_flights


async def main():
    # Configure fetch_mode inside FlightData
    flight_data = [
        FlightData(
            date="2026-09-18",
            from_airport="BRU",
            to_airport="VCE",
            fetch_mode="fallback"  # Uses Playwright under the hood to bypass consent/antibot
        )
    ]

    result = await get_flights(
        flight_data=flight_data,
        trip="one-way",
        passengers=Passengers(adults=1),
        seat="economy"
    )

    print(f"Found {len(result.flights)} flight offers.")
    for flight in result.flights:
        print(f"Price: {flight.price} | Airline: {flight.name} | Departure: {flight.departure}")


if __name__ == "__main__":
    asyncio.run(main())