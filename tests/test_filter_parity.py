"""The web app and widget rank trips with web/filter.js; the CLI ranks with
flight_monitor/find_round_trips.py. They must produce the same trips in the
same order, or the CLI stops being a reliable reference for what the widget shows.
"""

import json
import shutil
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest

from flight_monitor import find_round_trips
from flight_monitor.flight_model import FlightDataset

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "mock_flights_BRU_VCE.json"
RUNNER = ROOT / "tests" / "filter_engine_runner.js"

# Option names follow web/filter.js. Each case overrides the defaults below.
DEFAULTS = {"from": "BRU", "to": "VCE", "minNights": 4, "maxNights": 10, "nonstopOnly": True, "saturdayIn": True}
CASES = [
    {},
    {"nonstopOnly": False, "saturdayIn": False, "minNights": 2, "maxNights": 14},
    {"tripContainsFrom": "2026-10-10", "tripContainsTo": "2026-10-14"},
    {"depWeekdays": [1, 4], "depAfterHour": 9},
    {"earliestDeparture": "08:30", "airlines": "Brussels"},
]


def python_args(js: dict) -> Namespace:
    """Translate filter.js options into the argparse namespace find_round_trips expects."""
    return Namespace(
        origin=js["from"],
        destination=js["to"],
        min_nights=js["minNights"],
        max_nights=js["maxNights"],
        saturday_in=js["saturdayIn"],
        nonstop=js["nonstopOnly"],
        airlines=js.get("airlines", ""),
        earliest_departure=js.get("earliestDeparture", ""),
        dep_weekdays=js.get("depWeekdays", []),
        dep_after_hour=js.get("depAfterHour", 0),
        search_from="",
        search_to="",
        include_from=js.get("tripContainsFrom", ""),
        include_to=js.get("tripContainsTo", ""),
    )


def trip_key(out_id, ret_id, nights, price, out_date, ret_date):
    return (out_id, ret_id, nights, price, out_date, ret_date)


@pytest.fixture(scope="module")
def raw_flights():
    return json.loads(DATA.read_text())["flights"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required to run web/filter.js")
@pytest.mark.parametrize("overrides", CASES, ids=lambda c: json.dumps(c, sort_keys=True))
def test_web_engine_matches_python_reference(raw_flights, overrides, monkeypatch):
    js_options = {**DEFAULTS, **overrides}

    # Python reference
    dataset = FlightDataset.from_dict({"metadata": {}, "flights": raw_flights})
    args = python_args(js_options)
    monkeypatch.setattr(find_round_trips, "ARGS", args)
    outbound = [f for f in dataset.flights if f.origin == "BRU" and f.destination == "VCE"]
    inbound = [f for f in dataset.flights if f.origin == "VCE" and f.destination == "BRU"]
    py = [
        trip_key(c["outbound"]["flight_id"], c["return"]["flight_id"], c["nights"],
                 c["price"], c["outbound_date"], c["return_date"])
        for c in find_round_trips.compute(outbound, inbound)
    ]

    # web/filter.js, run under node exactly as the widget evaluates it
    proc = subprocess.run(
        ["node", str(RUNNER)],
        input=json.dumps({"flights": raw_flights, "options": js_options}),
        capture_output=True, text=True, check=True,
    )
    js = [
        trip_key(c["out"]["flight_id"], c["ret"]["flight_id"], c["nights"],
                 c["price"], c["outDate"], c["retDate"])
        for c in json.loads(proc.stdout)
    ]

    assert py, "reference produced no trips; the case tests nothing"
    assert js == py
