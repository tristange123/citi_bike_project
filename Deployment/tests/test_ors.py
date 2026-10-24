import os
import unittest
from unittest import mock

import requests

from backend import ors


def response(payload, status=200):
    resp = mock.Mock()
    resp.json.return_value = payload
    resp.raise_for_status.side_effect = None if status < 400 else requests.HTTPError(f"{status}")
    return resp


@mock.patch.dict(os.environ, {"ORS_API_KEY": "test-key"})
class OrsTest(unittest.TestCase):
    def setUp(self):
        ors._directions_cache.clear()

    @mock.patch.dict(os.environ, {"ORS_API_KEY": ""})
    def test_missing_key_returns_none_without_calling(self):
        with mock.patch("requests.post") as post:
            self.assertIsNone(ors.matrix("walk", [(40.7, -74.0)], [(40.71, -74.0)]))
            self.assertIsNone(ors.directions("bike", (40.7, -74.0), (40.71, -74.0)))
            post.assert_not_called()

    def test_matrix_sends_lon_lat_and_parses(self):
        payload = {"durations": [[10.0, 20.0]], "distances": [[100.0, 200.0]]}
        with mock.patch("requests.post", return_value=response(payload)) as post:
            seconds, meters = ors.matrix("bike", [(40.7, -74.0)], [(40.71, -74.01), (40.72, -74.02)])
        body = post.call_args.kwargs["json"]
        self.assertIn("/v2/matrix/cycling-regular", post.call_args.args[0])
        self.assertEqual(body["locations"][0], [-74.0, 40.7])
        self.assertEqual(body["sources"], [0])
        self.assertEqual(body["destinations"], [1, 2])
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "test-key")
        self.assertEqual(seconds.tolist(), [[10.0, 20.0]])
        self.assertEqual(meters.tolist(), [[100.0, 200.0]])

    def test_matrix_unroutable_cell_returns_none(self):
        payload = {"durations": [[10.0, None]], "distances": [[100.0, None]]}
        with mock.patch("requests.post", return_value=response(payload)):
            self.assertIsNone(ors.matrix("walk", [(40.7, -74.0)], [(40.71, -74.0), (40.72, -74.0)]))

    def test_directions_flips_coordinates_and_caches(self):
        payload = {"features": [{
            "geometry": {"coordinates": [[-74.0, 40.7], [-74.005, 40.705], [-74.01, 40.71]]},
            "properties": {"summary": {"distance": 1500.0, "duration": 400.0}},
        }]}
        with mock.patch("requests.post", return_value=response(payload)) as post:
            first = ors.directions("walk", (40.7, -74.0), (40.71, -74.01))
            second = ors.directions("walk", (40.7000001, -74.0), (40.71, -74.01))
        self.assertIn("/v2/directions/foot-walking/geojson", post.call_args.args[0])
        self.assertEqual(first["geometry"][0], [40.7, -74.0])
        self.assertEqual(first["meters"], 1500.0)
        self.assertEqual(first["seconds"], 400.0)
        self.assertIs(first, second)
        post.assert_called_once()

    def test_http_error_returns_none_and_is_not_cached(self):
        with mock.patch("requests.post", return_value=response({}, status=429)) as post:
            self.assertIsNone(ors.directions("bike", (40.7, -74.0), (40.71, -74.0)))
            self.assertIsNone(ors.directions("bike", (40.7, -74.0), (40.71, -74.0)))
        self.assertEqual(post.call_count, 2)

    def test_timeout_returns_none(self):
        with mock.patch("requests.post", side_effect=requests.Timeout("slow")):
            self.assertIsNone(ors.matrix("walk", [(40.7, -74.0)], [(40.71, -74.0)]))


if __name__ == "__main__":
    unittest.main()
