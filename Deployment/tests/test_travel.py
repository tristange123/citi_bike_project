import unittest

from backend.travel import DETOUR_FACTOR, haversine_meters, path_meters, walk_seconds


GRAND_ARMY_PLAZA = (40.7643971, -73.97371465)
BROADWAY_BATTERY = (40.70463334, -74.01361706)


class TravelTest(unittest.TestCase):
    def test_haversine_known_distance(self):
        meters = haversine_meters(*GRAND_ARMY_PLAZA, *BROADWAY_BATTERY)
        self.assertAlmostEqual(meters, 7_470, delta=100)

    def test_path_applies_detour(self):
        straight = haversine_meters(*GRAND_ARMY_PLAZA, *BROADWAY_BATTERY)
        self.assertAlmostEqual(path_meters(*GRAND_ARMY_PLAZA, *BROADWAY_BATTERY), straight * DETOUR_FACTOR)

    def test_zero_distance(self):
        self.assertEqual(walk_seconds(path_meters(*GRAND_ARMY_PLAZA, *GRAND_ARMY_PLAZA)), 0)


if __name__ == "__main__":
    unittest.main()
