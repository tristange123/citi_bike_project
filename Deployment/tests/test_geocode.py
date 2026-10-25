import unittest
from unittest import mock

from backend import geocode


BOUNDS = {"lat": (40.70, 40.74), "lon": (-74.02, -73.97)}
ALLEN = {"label": "200 ALLEN STREET, New York, NY, USA", "lat": 40.7226, "lon": -73.9885}
BROOKLYN = {"label": "40 BOND STREET, Brooklyn, NY, USA", "lat": 40.6886, "lon": -73.984}
MARKET = {"label": "Essex Market, New York, NY, USA", "lat": 40.718, "lon": -73.988}


def run_search(text, addresses, places):
    with mock.patch.object(geocode, "_nyc_geosearch", return_value=addresses), \
            mock.patch.object(geocode.ors, "autocomplete", return_value=places):
        return geocode.search(text, BOUNDS)


class GeocodeTest(unittest.TestCase):
    def setUp(self):
        geocode._cache.clear()

    def test_clean_label_title_cases_and_drops_country(self):
        self.assertEqual(geocode.clean_label(ALLEN["label"]), "200 Allen Street, New York, NY")
        self.assertEqual(geocode.clean_label(MARKET["label"]), "Essex Market, New York, NY")

    def test_drops_results_outside_bounds(self):
        labels = [r["label"] for r in run_search("40 Bond", [BROOKLYN, ALLEN], [])]
        self.assertEqual(labels, ["200 Allen Street, New York, NY"])

    def test_house_number_puts_addresses_first(self):
        self.assertEqual(run_search("200 Allen", [ALLEN], [MARKET])[0]["label"], "200 Allen Street, New York, NY")
        self.assertEqual(run_search("Essex", [ALLEN], [MARKET])[0]["label"], "Essex Market, New York, NY")

    def test_dedupes_and_survives_missing_ors(self):
        results = run_search("200 Allen", [ALLEN, dict(ALLEN)], None)
        self.assertEqual(len(results), 1)


if __name__ == "__main__":
    unittest.main()
