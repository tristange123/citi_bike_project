"""Address search for dropping pins by typing.

Two free geocoders cover each other's gaps: NYC GeoSearch (NYC City Planning, no key) knows
street addresses but few places, and OpenRouteService knows places but not house numbers.
Both are queried at once and merged, with results outside the service area dropped.
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import requests

from . import ors


NYC_GEOSEARCH_URL = "https://geosearch.planninglabs.nyc/v2/autocomplete"
REQUEST_TIMEOUT_SECONDS = 5
MAX_RESULTS = 6
CACHE_SIZE = 512

logger = logging.getLogger(__name__)

# NYC GeoSearch takes 1-3 s per request, so repeat queries (backspacing, retyping) come from memory.
_cache: dict[tuple, list[dict]] = {}
_cache_lock = threading.Lock()


def _nyc_geosearch(text: str) -> list[dict]:
    try:
        response = requests.get(NYC_GEOSEARCH_URL, params={"text": text}, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return [
            {"label": feature["properties"]["label"], "lat": lat, "lon": lon}
            for feature in response.json()["features"]
            for lon, lat, *_ in [feature["geometry"]["coordinates"]]
        ]
    except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
        logger.warning("NYC GeoSearch request failed: %s", exc)
        return []


def clean_label(label: str) -> str:
    """'200 ALLEN STREET, New York, NY, USA' -> '200 Allen Street, New York, NY'."""
    parts = [part.strip() for part in label.split(",")]
    if parts and parts[-1] == "USA":
        parts.pop()
    if parts and parts[0].isupper():
        parts[0] = parts[0].title()
    return ", ".join(parts)


def search(text: str, bounds: dict[str, tuple[float, float]]) -> list[dict]:
    key = (" ".join(text.lower().split()), tuple(bounds["lat"]), tuple(bounds["lon"]))
    with _cache_lock:
        if key in _cache:
            return _cache[key]

    results = _search(text, bounds)
    with _cache_lock:
        if len(_cache) >= CACHE_SIZE:
            _cache.clear()
        _cache[key] = results
    return results


def _search(text: str, bounds: dict[str, tuple[float, float]]) -> list[dict]:
    (lat_min, lat_max), (lon_min, lon_max) = bounds["lat"], bounds["lon"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        addresses = pool.submit(_nyc_geosearch, text)
        places = pool.submit(ors.autocomplete, text, bounds)
        address_results, place_results = addresses.result(), places.result() or []

    # A leading house number means the user is typing an address.
    ordered = address_results + place_results if text[:1].isdigit() else place_results + address_results

    results: list[dict] = []
    seen: set[str] = set()
    for result in ordered:
        if not (lat_min <= result["lat"] <= lat_max and lon_min <= result["lon"] <= lon_max):
            continue
        label = clean_label(result["label"])
        if label.lower() in seen:
            continue
        seen.add(label.lower())
        results.append({"label": label, "lat": result["lat"], "lon": result["lon"]})
        if len(results) == MAX_RESULTS:
            break
    return results
