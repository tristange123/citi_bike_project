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



class ProviderTest(unittest.TestCase):
    """Matrix/directions providers replace estimates, and None falls back to them."""

    far = 40.70 + 5 * KM

    def network(self):
        # Two equivalent pickups side by side, one dropoff.
        return make_network([
            (40.70, -74.0000, 10, 5),
            (40.70, -74.0005, 10, 5),
            (self.far, -74.00, 5, 10),
        ])

    def plan(self, network, **providers):
        return plan_routes(network, (40.70, -74.00), (self.far, -74.00), DEPART, live_counts(network), UTC, **providers)

    def test_matrix_bike_times_drive_ranking(self):
        network = self.network()
        baseline = self.plan(network)
        self.assertEqual(baseline["routes"][0]["pickup"]["name"], "S0")

        def matrix(mode, sources, destinations):
            seconds = np.full((len(sources), len(destinations)), 60.0)
            if mode == "bike":
                seconds[0, :] = 5000  # S0's ride is blocked by, say, a river
                seconds[1, :] = 900
            return seconds, seconds * 4

        plan = self.plan(network, matrix_provider=matrix)
        fastest = plan["routes"][0]
        self.assertEqual(fastest["pickup"]["name"], "S1")
        self.assertEqual(fastest["legs"][1]["seconds"], 900 + 120)
        self.assertFalse(any(leg["estimated"] for leg in fastest["legs"]))

    def test_failed_providers_fall_back_to_estimates(self):
        network = self.network()
        baseline = self.plan(network)
        plan = self.plan(network, matrix_provider=lambda *a: None, directions_provider=lambda *a: None)
        self.assertEqual(plan, baseline)
        for route in plan["routes"]:
            for leg in route["legs"]:
                self.assertTrue(leg["estimated"])
                self.assertEqual(len(leg["geometry"]), 2)

    def test_directions_set_geometry_and_relabel(self):
        network = self.network()
        calls = []

        def directions(mode, start, end):
            calls.append((mode, start, end))
            # The S0 ride turns out much slower on real streets.
            slow = mode == "bike" and start == (40.70, -74.0000)
            return {"geometry": [list(start), [0.0, 0.0], list(end)], "meters": 1000.0, "seconds": 4000.0 if slow else 300.0}

        plan = self.plan(network, directions_provider=directions)
        bike_routes = [r for r in plan["routes"] if r["pickup"]]
        self.assertEqual(bike_routes[0]["label"], "fastest")
        self.assertEqual(bike_routes[0]["pickup"]["name"], "S1")
        self.assertEqual(bike_routes[1]["pickup"]["name"], "S0")
        self.assertEqual(bike_routes[1]["label"], "alternate")
        for route in plan["routes"]:
            self.assertEqual(route["totalSeconds"], sum(leg["seconds"] for leg in route["legs"]))
            for leg in route["legs"]:
                self.assertEqual(len(leg["geometry"]), 3)
                self.assertFalse(leg["estimated"])
        # Legs shared between routes (walk to the single dropoff's destination) are fetched once.
        self.assertEqual(len(calls), len(set(calls)))


if __name__ == "__main__":
    unittest.main()
