"""OpenRouteService client for real walk/bike travel times and street-following route geometry.

Every function returns None when ORS_API_KEY is unset or a request fails (quota, timeout, no
route), and callers fall back to the straight-line estimates in travel.py.
"""

import logging
import os
import threading

import numpy as np
import requests


ORS_BASE_URL = "https://api.openrouteservice.org"
PROFILES = {"walk": "foot-walking", "bike": "cycling-regular"}
REQUEST_TIMEOUT_SECONDS = 5
DIRECTIONS_CACHE_SIZE = 2048

logger = logging.getLogger(__name__)

# Only successful lookups are cached, so a quota error is retried on the next trip.
_directions_cache: dict[tuple, dict] = {}
_cache_lock = threading.Lock()


def _post(path: str, body: dict) -> dict | None:
    api_key = os.getenv("ORS_API_KEY", "").strip()
    if not api_key:
        return None

    try:
        response = requests.post(
            f"{ORS_BASE_URL}{path}",
            json=body,
            headers={"Authorization": api_key},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("ORS request to %s failed: %s", path, exc)
        return None


def _get(path: str, params: dict) -> dict | None:
    api_key = os.getenv("ORS_API_KEY", "").strip()
    if not api_key:
        return None

    try:
        response = requests.get(
            f"{ORS_BASE_URL}{path}",
            params=params,
            headers={"Authorization": api_key},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("ORS request to %s failed: %s", path, exc)
        return None


def autocomplete(text: str, bounds: dict[str, tuple[float, float]], size: int = 6) -> list[dict] | None:
    """[{"label", "lat", "lon"}, ...] for places matching text inside bounds {"lat": (min, max), "lon": (min, max)}."""
    (lat_min, lat_max), (lon_min, lon_max) = bounds["lat"], bounds["lon"]
    data = _get(
        "/geocode/autocomplete",
        {
            "text": text,
            "size": size,
            "boundary.rect.min_lat": lat_min,
            "boundary.rect.max_lat": lat_max,
            "boundary.rect.min_lon": lon_min,
            "boundary.rect.max_lon": lon_max,
            "focus.point.lat": (lat_min + lat_max) / 2,
            "focus.point.lon": (lon_min + lon_max) / 2,
        },
    )
    if data is None:
        return None

    try:
        return [
            {"label": feature["properties"]["label"], "lat": lat, "lon": lon}
            for feature in data["features"]
            for lon, lat, *_ in [feature["geometry"]["coordinates"]]
        ]
    except (KeyError, TypeError, ValueError):
        return None


def matrix(
    mode: str,
    sources: list[tuple[float, float]],
    destinations: list[tuple[float, float]],
) -> tuple[np.ndarray, np.ndarray] | None:
    """(seconds, meters) arrays shaped (len(sources), len(destinations)) for mode "walk" or "bike"."""
    points = list(sources) + list(destinations)
    data = _post(
        f"/v2/matrix/{PROFILES[mode]}",
        {
            "locations": [[lon, lat] for lat, lon in points],
            "sources": list(range(len(sources))),
            "destinations": list(range(len(sources), len(points))),
            "metrics": ["duration", "distance"],
            "units": "m",
        },
    )
    if data is None:
        return None

    try:
        seconds = np.array(data["durations"], dtype=float)
        meters = np.array(data["distances"], dtype=float)
    except (KeyError, TypeError, ValueError):
        return None
    # ORS reports unroutable pairs as null, which numpy turns into NaN.
    if seconds.shape != (len(sources), len(destinations)) or np.isnan(seconds).any() or np.isnan(meters).any():
        return None
    return seconds, meters


def directions(mode: str, start: tuple[float, float], end: tuple[float, float]) -> dict | None:
    """{"geometry": [[lat, lon], ...], "meters", "seconds"} for one leg, or None."""
    # ~1 m rounding lets repeat trips and legs shared between routes hit the cache.
    key = (mode, round(start[0], 5), round(start[1], 5), round(end[0], 5), round(end[1], 5))
    with _cache_lock:
        if key in _directions_cache:
            return _directions_cache[key]

    _, lat1, lon1, lat2, lon2 = key
    data = _post(f"/v2/directions/{PROFILES[mode]}/geojson", {"coordinates": [[lon1, lat1], [lon2, lat2]]})
    if data is None:
        return None

    try:
        feature = data["features"][0]
        summary = feature["properties"]["summary"]
        result = {
            # GeoJSON is [lon, lat]; Leaflet wants [lat, lon].
            "geometry": [[lat, lon] for lon, lat, *_ in feature["geometry"]["coordinates"]],
            "meters": float(summary.get("distance", 0.0)),
            "seconds": float(summary.get("duration", 0.0)),
        }
    except (KeyError, IndexError, TypeError, ValueError):
        return None

    with _cache_lock:
        if len(_directions_cache) >= DIRECTIONS_CACHE_SIZE:
            _directions_cache.clear()
        _directions_cache[key] = result
    return result
