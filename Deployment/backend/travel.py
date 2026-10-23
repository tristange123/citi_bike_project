"""Distance-based travel time estimates.

There is no routing engine: every leg is straight-line distance scaled by a detour factor.
This works well on the Manhattan street grid. It underestimates trips that cross rivers or
detour around parks, because the real path is much longer than the straight line.
"""

import numpy as np


EARTH_RADIUS_METERS = 6_371_000

# Street paths on a grid run roughly 1.3x the straight-line distance (between L2 and L1).
DETOUR_FACTOR = 1.3
WALK_SPEED_MPS = 1.4  # ~5 km/h
BIKE_SPEED_MPS = 4.2  # ~15 km/h, a classic bike in city traffic
UNLOCK_SECONDS = 60
DOCK_SECONDS = 60


def haversine_meters(lat1, lon1, lat2, lon2):
    """Great-circle distance in meters; accepts scalars or broadcastable numpy arrays."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = (
        np.sin((lat2 - lat1) / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_METERS * np.arcsin(np.sqrt(a))


def path_meters(lat1, lon1, lat2, lon2):
    """Estimated street distance between two points."""
    return haversine_meters(lat1, lon1, lat2, lon2) * DETOUR_FACTOR


def walk_seconds(meters):
    return meters / WALK_SPEED_MPS


def bike_seconds(meters):
    return meters / BIKE_SPEED_MPS
