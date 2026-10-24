"""Walk -> bike -> walk route planning over station candidates near two pins."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from .travel import (
    DOCK_SECONDS,
    UNLOCK_SECONDS,
    bike_seconds,
    haversine_meters,
    path_meters,
    walk_seconds,
)


CANDIDATES_PER_PIN = 5
SEARCH_RADIUS_METERS = 800
MAX_SEARCH_RADIUS_METERS = 3200
MAX_BIKE_ROUTES = 3
# "Most reliable" may cost up to this much more expected time than the fastest route.
RELIABLE_TIME_SLACK = 1.25
# Even an adjacent backup station costs a couple of minutes of checking and walking.
MIN_FALLBACK_SECONDS = 120

# (station_idx, kinds, timestamps) -> expected count of bikes/docks at each query.
CountPredictor = Callable[[np.ndarray, np.ndarray, list[datetime]], np.ndarray]
# (mode, sources, destinations) -> (seconds, meters) arrays, or None to use estimates.
MatrixProvider = Callable[[str, list[tuple[float, float]], list[tuple[float, float]]], tuple[np.ndarray, np.ndarray] | None]
# (mode, start, end) -> {"geometry": [[lat, lon], ...], "meters", "seconds"}, or None to keep the estimate.
DirectionsProvider = Callable[[str, tuple[float, float], tuple[float, float]], dict | None]


def find_candidates(network: pd.DataFrame, lat: float, lon: float, available: np.ndarray) -> np.ndarray:
    """Indices of up to CANDIDATES_PER_PIN nearest available stations, widening the radius if empty."""
    distances = haversine_meters(lat, lon, network["lat"].to_numpy(), network["lon"].to_numpy())
    radius = SEARCH_RADIUS_METERS
    while radius <= MAX_SEARCH_RADIUS_METERS:
        idx = np.flatnonzero(available & (distances <= radius))
        if idx.size:
            return idx[np.argsort(distances[idx])][:CANDIDATES_PER_PIN]
        radius *= 2
    return np.array([], dtype=int)


def fallback_seconds(network: pd.DataFrame, idx: np.ndarray, available: np.ndarray) -> np.ndarray:
    """Walk time from each station in idx to the nearest *other* available station."""
    lats = network["lat"].to_numpy()
    lons = network["lon"].to_numpy()
    others = np.flatnonzero(available)
    if others.size == 0:
        return np.full(len(idx), float(walk_seconds(MAX_SEARCH_RADIUS_METERS)))

    meters = path_meters(lats[idx, None], lons[idx, None], lats[None, others], lons[None, others])
    meters[idx[:, None] == others[None, :]] = np.inf
    nearest = meters.min(axis=1)
    nearest[np.isinf(nearest)] = MAX_SEARCH_RADIUS_METERS
    return np.maximum(walk_seconds(nearest), MIN_FALLBACK_SECONDS)


def probability_at_least_one(expected_count: np.ndarray) -> np.ndarray:
    """Poisson chance that at least one bike/dock is free given its expected count."""
    return 1 - np.exp(-np.maximum(expected_count, 0))


def _point(name: str, lat: float, lon: float) -> dict:
    return {"name": name, "lat": float(lat), "lon": float(lon)}


def _leg(mode: str, start: dict, end: dict, meters: float, seconds: float, estimated: bool = True) -> dict:
    return {
        "mode": mode,
        "start": start,
        "end": end,
        "meters": round(float(meters)),
        "seconds": round(float(seconds)),
        # A straight segment until directions replace it with the street path.
        "geometry": [[start["lat"], start["lon"]], [end["lat"], end["lon"]]],
        "estimated": estimated,
    }


def _travel_times(
    matrix_provider: MatrixProvider | None,
    mode: str,
    sources: list[tuple[float, float]],
    destinations: list[tuple[float, float]],
) -> tuple[np.ndarray, np.ndarray, bool]:
    """(seconds, meters, estimated) from every source to every destination."""
    if matrix_provider is not None:
        result = matrix_provider(mode, sources, destinations)
        if result is not None:
            seconds, meters = result
            return np.asarray(seconds, dtype=float), np.asarray(meters, dtype=float), False

    src = np.asarray(sources, dtype=float)
    dst = np.asarray(destinations, dtype=float)
    meters = path_meters(src[:, None, 0], src[:, None, 1], dst[None, :, 0], dst[None, :, 1])
    seconds = walk_seconds(meters) if mode == "walk" else bike_seconds(meters)
    return seconds, meters, True


def _iso(timestamp: datetime, tz) -> str:
    return timestamp.astimezone(tz).isoformat()


def _pick_routes(order: np.ndarray, expected: np.ndarray, reliability: np.ndarray, pairs: np.ndarray) -> list[tuple[int, str]]:
    """Choose up to MAX_BIKE_ROUTES pair indices with distinct stations, labelled for the UI.

    Routes sharing neither station with earlier picks are preferred; when the pins have too few
    nearby stations for that, a route only needs to introduce one new station.
    """
    chosen: list[tuple[int, str]] = [(int(order[0]), "fastest")]

    def is_distinct(candidate: int, strict: bool) -> bool:
        o, d = pairs[candidate]
        new_pickup = all(pairs[c][0] != o for c, _ in chosen)
        new_dropoff = all(pairs[c][1] != d for c, _ in chosen)
        return (new_pickup and new_dropoff) if strict else (new_pickup or new_dropoff)

    fastest = order[0]
    for strict in (True, False):
        reliable = [
            p for p in order[1:]
            if is_distinct(p, strict)
            and expected[p] <= expected[fastest] * RELIABLE_TIME_SLACK
            and reliability[p] > reliability[fastest]
        ]
        if reliable:
            chosen.append((int(max(reliable, key=lambda p: reliability[p])), "most reliable"))
            break

    for strict in (True, False):
        for p in order[1:]:
            if len(chosen) >= MAX_BIKE_ROUTES:
                return chosen
            if is_distinct(p, strict):
                chosen.append((int(p), "alternate"))
    return chosen


def _relabel(bike_routes: list[dict]) -> list[dict]:
    """Sort bike routes by expected time and reassign fastest / most reliable / alternate labels."""
    bike_routes = sorted(bike_routes, key=lambda route: route["expectedSeconds"])
    if not bike_routes:
        return bike_routes

    fastest = bike_routes[0]
    reliable = [
        route for route in bike_routes[1:]
        if route["expectedSeconds"] <= fastest["expectedSeconds"] * RELIABLE_TIME_SLACK
        and route["reliability"] > fastest["reliability"]
    ]
    most_reliable = max(reliable, key=lambda route: route["reliability"]) if reliable else None
    for route in bike_routes:
        route["label"] = (
            "fastest" if route is fastest else "most reliable" if route is most_reliable else "alternate"
        )
    return bike_routes


def _apply_directions(routes: list[dict], directions_provider: DirectionsProvider, depart: datetime, tz) -> bool:
    """Swap estimated legs for real street paths and times; returns whether any leg changed."""
    def leg_key(leg: dict) -> tuple:
        return (leg["mode"], (leg["start"]["lat"], leg["start"]["lon"]), (leg["end"]["lat"], leg["end"]["lon"]))

    keys = list(dict.fromkeys(leg_key(leg) for route in routes for leg in route["legs"]))
    with ThreadPoolExecutor(max_workers=len(keys)) as pool:
        results = dict(zip(keys, pool.map(lambda key: directions_provider(*key), keys)))

    changed = False
    for route in routes:
        route_changed = False
        for leg in route["legs"]:
            result = results[leg_key(leg)]
            if result is None:
                continue
            overhead = UNLOCK_SECONDS + DOCK_SECONDS if leg["mode"] == "bike" else 0
            leg.update(
                geometry=result["geometry"],
                meters=round(result["meters"]),
                seconds=round(result["seconds"] + overhead),
                estimated=False,
            )
            route_changed = True
        if not route_changed:
            continue
        changed = True

        # The availability penalty (expected - total) carries over unchanged.
        total = sum(leg["seconds"] for leg in route["legs"])
        route["expectedSeconds"] += total - route["totalSeconds"]
        route["totalSeconds"] = total
        route["arriveAt"] = _iso(depart + timedelta(seconds=total), tz)
    return changed


def plan_routes(
    network: pd.DataFrame,
    origin: tuple[float, float],
    destination: tuple[float, float],
    depart: datetime,
    predict_counts: CountPredictor,
    tz,
    matrix_provider: MatrixProvider | None = None,
    directions_provider: DirectionsProvider | None = None,
) -> dict:
    """Ranked route options from origin to destination: up to 3 bike routes plus walking only.

    Candidates are always chosen by straight-line distance. Providers, when given, supply real
    travel times for ranking (matrix) and street paths for the displayed legs (directions);
    anything they cannot answer falls back to the straight-line estimates.
    """
    origin_point = _point("Start", *origin)
    destination_point = _point("Destination", *destination)

    walk_only_meters = float(path_meters(*origin, *destination))
    walk_only_seconds = float(walk_seconds(walk_only_meters))
    walk_route = {
        "label": "walk only",
        "totalSeconds": round(walk_only_seconds),
        "expectedSeconds": round(walk_only_seconds),
        "reliability": 1.0,
        "departAt": _iso(depart, tz),
        "arriveAt": _iso(depart + timedelta(seconds=walk_only_seconds), tz),
        "legs": [_leg("walk", origin_point, destination_point, walk_only_meters, walk_only_seconds)],
        "pickup": None,
        "dropoff": None,
    }

    has_bikes = network["bikes"].to_numpy() > 0
    has_docks = network["docks"].to_numpy() > 0
    origin_idx = find_candidates(network, *origin, has_bikes)
    dest_idx = find_candidates(network, *destination, has_docks)

    pairs = np.array(
        [(i, j) for i in range(len(origin_idx)) for j in range(len(dest_idx)) if origin_idx[i] != dest_idx[j]],
        dtype=int,
    ).reshape(-1, 2)
    if len(pairs) == 0:
        routes = [walk_route]
        if directions_provider is not None:
            _apply_directions(routes, directions_provider, depart, tz)
        return {"routes": routes, "recommendedIndex": 0}

    lats = network["lat"].to_numpy()
    lons = network["lon"].to_numpy()
    origin_stations = list(zip(lats[origin_idx], lons[origin_idx]))
    dest_stations = list(zip(lats[dest_idx], lons[dest_idx]))

    # Three independent lookups: pin A -> pickups (walk), pickups -> dropoffs (bike), dropoffs -> pin B (walk).
    lookups = [
        ("walk", [origin], origin_stations),
        ("bike", origin_stations, dest_stations),
        ("walk", dest_stations, [destination]),
    ]
    with ThreadPoolExecutor(max_workers=len(lookups)) as pool:
        to_pickup, bike_grid, from_dropoff = pool.map(
            lambda lookup: _travel_times(matrix_provider, *lookup), lookups
        )
    walk_a, walk_a_meters, walk_a_est = to_pickup[0][0], to_pickup[1][0], to_pickup[2]
    ride_all, bike_meters_all, bike_est = bike_grid
    walk_b, walk_b_meters, walk_b_est = from_dropoff[0][:, 0], from_dropoff[1][:, 0], from_dropoff[2]

    pi, pj = pairs[:, 0], pairs[:, 1]
    bike_meters = bike_meters_all[pi, pj]
    ride = ride_all[pi, pj]
    seconds_to_dock = walk_a[pi] + UNLOCK_SECONDS + ride
    total = seconds_to_dock + DOCK_SECONDS + walk_b[pj]

    # One predictor call: bikes at each origin on arrival, docks at each destination on arrival.
    pickup_times = [depart + timedelta(seconds=float(s)) for s in walk_a]
    dropoff_times = [depart + timedelta(seconds=float(s)) for s in seconds_to_dock]
    counts = predict_counts(
        np.concatenate([origin_idx, dest_idx[pj]]),
        np.array(["bikes"] * len(origin_idx) + ["docks"] * len(pairs)),
        pickup_times + dropoff_times,
    )
    expected_bikes = counts[: len(origin_idx)]
    expected_docks = counts[len(origin_idx):]

    p_bike = probability_at_least_one(expected_bikes)[pi]
    p_dock = probability_at_least_one(expected_docks)
    reliability = p_bike * p_dock
    expected = (
        total
        + (1 - p_bike) * fallback_seconds(network, origin_idx, has_bikes)[pi]
        + (1 - p_dock) * fallback_seconds(network, dest_idx, has_docks)[pj]
    )

    order = np.argsort(expected)
    routes = []
    for p, label in _pick_routes(order, expected, reliability, pairs):
        i, j = pairs[p]
        o_row = network.iloc[origin_idx[i]]
        d_row = network.iloc[dest_idx[j]]
        pickup_point = _point(o_row["name"], o_row["lat"], o_row["lon"])
        dropoff_point = _point(d_row["name"], d_row["lat"], d_row["lon"])
        routes.append(
            {
                "label": label,
                "totalSeconds": round(float(total[p])),
                "expectedSeconds": round(float(expected[p])),
                "reliability": round(float(reliability[p]), 3),
                "departAt": _iso(depart, tz),
                "arriveAt": _iso(depart + timedelta(seconds=float(total[p])), tz),
                "legs": [
                    _leg("walk", origin_point, pickup_point, walk_a_meters[i], walk_a[i], walk_a_est),
                    _leg(
                        "bike", pickup_point, dropoff_point, bike_meters[p],
                        ride[p] + UNLOCK_SECONDS + DOCK_SECONDS, bike_est,
                    ),
                    _leg("walk", dropoff_point, destination_point, walk_b_meters[j], walk_b[j], walk_b_est),
                ],
                "pickup": {
                    **pickup_point,
                    "shortname": str(o_row["shortname"]),
                    "modeled": bool(o_row["modeled"]),
                    "bikesNow": int(o_row["bikes"]),
                    "ebikesNow": int(o_row["ebikes"]),
                    "docksNow": int(o_row["docks"]),
                    "expectedAtArrival": round(float(expected_bikes[i]), 1),
                },
                "dropoff": {
                    **dropoff_point,
                    "shortname": str(d_row["shortname"]),
                    "modeled": bool(d_row["modeled"]),
                    "bikesNow": int(d_row["bikes"]),
                    "ebikesNow": int(d_row["ebikes"]),
                    "docksNow": int(d_row["docks"]),
                    "expectedAtArrival": round(float(expected_docks[p]), 1),
                },
            }
        )

    if directions_provider is not None and _apply_directions(routes + [walk_route], directions_provider, depart, tz):
        # Real times can reorder routes picked on estimates, e.g. a river crossing that was optimistic.
        routes = _relabel(routes)

    routes.append(walk_route)
    recommended = min(range(len(routes)), key=lambda k: routes[k]["expectedSeconds"])
    return {"routes": routes, "recommendedIndex": recommended}
