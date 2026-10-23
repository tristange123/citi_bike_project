import unittest
from datetime import datetime

import numpy as np
import pandas as pd
from zoneinfo import ZoneInfo

from backend.planner import plan_routes


UTC = ZoneInfo("UTC")
DEPART = datetime(2026, 10, 23, 14, 0, tzinfo=UTC)
# ~0.009 degrees of latitude is ~1 km.
KM = 0.009


def make_network(rows):
    return pd.DataFrame(
        [
            {"shortname": str(i), "name": f"S{i}", "lat": lat, "lon": lon, "bikes": bikes,
             "ebikes": 0, "docks": docks, "modeled": False}
            for i, (lat, lon, bikes, docks) in enumerate(rows)
        ]
    )


def live_counts(network):
    def predict(idx, kinds, timestamps):
        return np.where(kinds == "bikes", network["bikes"].to_numpy()[idx], network["docks"].to_numpy()[idx]).astype(float)
    return predict


class PlannerTest(unittest.TestCase):
    def plan(self, network, origin, destination):
        return plan_routes(network, origin, destination, DEPART, live_counts(network), UTC)

    def test_no_station_near_pins_returns_walk_only(self):
        network = make_network([(40.70, -74.00, 5, 5)])
        plan = self.plan(network, (40.80, -73.95), (40.81, -73.95))
        self.assertEqual([r["label"] for r in plan["routes"]], ["walk only"])
        self.assertEqual(plan["recommendedIndex"], 0)

    def test_short_trip_recommends_walking(self):
        base = 40.75
        network = make_network([(base + 0.1 * KM, -73.99, 5, 5), (base + 0.2 * KM, -73.99, 5, 5)])
        plan = self.plan(network, (base, -73.99), (base + 0.3 * KM, -73.99))
        self.assertEqual(plan["routes"][plan["recommendedIndex"]]["label"], "walk only")

    def test_long_trip_recommends_bike(self):
        network = make_network([(40.70, -74.00, 5, 5), (40.70 + 5 * KM, -74.00, 5, 5)])
        plan = self.plan(network, (40.70, -74.00), (40.70 + 5 * KM, -74.00))
        best = plan["routes"][plan["recommendedIndex"]]
        self.assertEqual(best["label"], "fastest")
        self.assertEqual([leg["mode"] for leg in best["legs"]], ["walk", "bike", "walk"])
        self.assertEqual(best["pickup"]["name"], "S0")
        self.assertEqual(best["dropoff"]["name"], "S1")

    def test_empty_stations_are_skipped_and_scarce_ones_penalized(self):
        far = 40.70 + 5 * KM
        network = make_network([
            (40.70, -74.00, 0, 5),             # empty: never a pickup
            (40.70 + 0.02 * KM, -74.00, 1, 5), # closest with bikes, but only one
            (40.70 + 0.05 * KM, -74.00, 15, 5), # slightly further, plenty of bikes
            (far, -74.00, 5, 5),
        ])
        plan = self.plan(network, (40.70, -74.00), (far, -74.00))
        bike_routes = [r for r in plan["routes"] if r["pickup"]]
        self.assertNotIn("S0", {r["pickup"]["name"] for r in bike_routes})
        by_pickup = {r["pickup"]["name"]: r for r in bike_routes}
        self.assertLess(by_pickup["S1"]["totalSeconds"], by_pickup["S2"]["totalSeconds"])
        self.assertGreater(by_pickup["S2"]["reliability"], by_pickup["S1"]["reliability"])
        self.assertEqual(bike_routes[0]["pickup"]["name"], "S2")

    def test_routes_use_distinct_stations(self):
        far = 40.70 + 5 * KM
        rows = [(40.70 + k * 0.05 * KM, -74.00, 10, 10) for k in range(5)]
        rows += [(far + k * 0.05 * KM, -74.00, 10, 10) for k in range(5)]
        plan = self.plan(make_network(rows), (40.70, -74.00), (far, -74.00))
        bike_routes = [r for r in plan["routes"] if r["pickup"]]
        self.assertEqual(len(bike_routes), 3)
        self.assertEqual(len({r["pickup"]["name"] for r in bike_routes}), 3)
        self.assertEqual(len({r["dropoff"]["name"] for r in bike_routes}), 3)


if __name__ == "__main__":
    unittest.main()
