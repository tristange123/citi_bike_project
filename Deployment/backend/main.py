import os
from datetime import datetime, timedelta
from functools import partial
from typing import Literal

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .forecast import (
    NY_TZ,
    UTC_TZ,
    apply_live_offset,
    build_forecast_timestamps,
    load_station_info,
    predict_counts,
    predict_raw,
    pull_live_station_data,
)
from . import ors
from .gbfs_cache import load_network
from .planner import plan_routes


# Rough NYC bounding box; pins outside it have no Citi Bike service.
SERVICE_AREA = {"lat": (40.45, 40.95), "lon": (-74.30, -73.65)}


class PredictionPoint(BaseModel):
    timestamp: str
    bikeAvailability: float
    dockAvailability: float


class StationPrediction(BaseModel):
    shortname: str
    name: str
    lat: float
    lon: float
    currentBikeAvailability: float | None
    currentBikesAvailable: int | None
    currentDocksAvailable: int | None
    predictions: list[PredictionPoint]


class PredictionResponse(BaseModel):
    generatedAt: str
    forecastStart: str
    forecastEnd: str
    stations: list[StationPrediction]


class RoutePoint(BaseModel):
    name: str
    lat: float
    lon: float


class RouteStation(RoutePoint):
    shortname: str
    modeled: bool
    bikesNow: int
    ebikesNow: int
    docksNow: int
    # Expected bikes at pickup or docks at dropoff when the rider gets there.
    expectedAtArrival: float


class RouteLeg(BaseModel):
    mode: Literal["walk", "bike"]
    start: RoutePoint
    end: RoutePoint
    meters: int
    seconds: int
    # [[lat, lon], ...] along the streets, or just [start, end] when no route was available.
    geometry: list[list[float]]
    # True when meters/seconds are straight-line estimates rather than OpenRouteService results.
    estimated: bool


class RouteOption(BaseModel):
    label: str
    totalSeconds: int
    # totalSeconds plus the expected cost of detouring when a bike or dock is unavailable.
    expectedSeconds: int
    reliability: float
    departAt: str
    arriveAt: str
    legs: list[RouteLeg]
    pickup: RouteStation | None
    dropoff: RouteStation | None


class RouteResponse(BaseModel):
    generatedAt: str
    routes: list[RouteOption]
    recommendedIndex: int


app = FastAPI(
    title="Citi Bike Forecast API",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "*").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/api/predictions", response_model=PredictionResponse)
def get_predictions() -> PredictionResponse:
    shortnames, station_meta = load_station_info()
    live_df = pull_live_station_data(shortnames)

    timestamps = build_forecast_timestamps()
    current_capacities = dict(zip(live_df["shortname"], live_df["percentage_available"]))
    current_bikes = dict(zip(live_df["shortname"], live_df["num_bikes_available"]))
    current_docks = dict(zip(live_df["shortname"], live_df["num_docks_available"]))
    now_utc = datetime.now(tz=UTC_TZ)

    station_names = [shortname for shortname in sorted(shortnames) if shortname in station_meta]

    # One row per (station, timestamp), station-major, so predictions reshape to (stations, timestamps).
    pred_df = pd.MultiIndex.from_product(
        [station_names, pd.DatetimeIndex(timestamps)],
        names=["shortname", "timestamp"],
    ).to_frame(index=False)
    raw_predictions = predict_raw(pred_df).reshape(len(station_names), len(timestamps))

    current_capacity_array = np.array(
        [current_capacities.get(shortname, np.nan) for shortname in station_names], dtype=float
    )
    seconds_ahead = np.array([(timestamp - now_utc).total_seconds() for timestamp in timestamps])
    updated_predictions = apply_live_offset(
        raw_predictions,
        raw_predictions[:, :1],
        current_capacity_array[:, None],
        seconds_ahead[None, :],
    )

    timestamp_strings = [timestamp.astimezone(NY_TZ).isoformat() for timestamp in timestamps]

    stations: list[StationPrediction] = []
    for shortname, station_predictions in zip(station_names, updated_predictions.tolist()):
        current_capacity = current_capacities.get(shortname)
        predictions = [
            PredictionPoint(
                timestamp=timestamp_string,
                bikeAvailability=round(value, 4),
                dockAvailability=round(1 - value, 4),
            )
            for timestamp_string, value in zip(timestamp_strings, station_predictions)
        ]

        meta = station_meta[shortname]
        stations.append(
            StationPrediction(
                shortname=shortname,
                name=meta["name"],
                lat=meta["lat"],
                lon=meta["lon"],
                currentBikeAvailability=(
                    round(float(current_capacity), 4) if current_capacity is not None else None
                ),
                currentBikesAvailable=(
                    int(current_bikes[shortname]) if shortname in current_bikes else None
                ),
                currentDocksAvailable=(
                    int(current_docks[shortname]) if shortname in current_docks else None
                ),
                predictions=predictions,
            )
        )

    return PredictionResponse(
        generatedAt=now_utc.astimezone(NY_TZ).isoformat(),
        forecastStart=timestamps[0].astimezone(NY_TZ).isoformat(),
        forecastEnd=timestamps[-1].astimezone(NY_TZ).isoformat(),
        stations=stations,
    )


def parse_point(value: str, field: str) -> tuple[float, float]:
    try:
        lat_text, lon_text = value.split(",")
        lat, lon = float(lat_text), float(lon_text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"'{field}' must be 'lat,lon'") from exc

    (lat_min, lat_max), (lon_min, lon_max) = SERVICE_AREA["lat"], SERVICE_AREA["lon"]
    if not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max):
        raise HTTPException(status_code=422, detail=f"'{field}' is outside the Citi Bike service area")
    return lat, lon


@app.get("/api/route", response_model=RouteResponse)
def get_route(
    origin: str = Query(alias="from", description="Start pin as 'lat,lon'"),
    destination: str = Query(alias="to", description="Destination pin as 'lat,lon'"),
    depart: datetime | None = Query(default=None, description="ISO departure time, defaults to now"),
) -> RouteResponse:
    origin_point = parse_point(origin, "from")
    destination_point = parse_point(destination, "to")

    now_utc = datetime.now(tz=UTC_TZ)
    if depart is None:
        depart_utc = now_utc
    else:
        depart_utc = (depart if depart.tzinfo else depart.replace(tzinfo=NY_TZ)).astimezone(UTC_TZ)
        if depart_utc < now_utc - timedelta(minutes=5) or depart_utc > now_utc + timedelta(days=7):
            raise HTTPException(status_code=422, detail="'depart' must be between now and 7 days ahead")
        depart_utc = max(depart_utc, now_utc)

    shortnames, _ = load_station_info()
    network = load_network(shortnames)
    plan = plan_routes(
        network,
        origin_point,
        destination_point,
        depart_utc,
        partial(predict_counts, network, now_utc=now_utc),
        NY_TZ,
        matrix_provider=ors.matrix,
        directions_provider=ors.directions,
    )
    return RouteResponse.model_validate({"generatedAt": now_utc.astimezone(NY_TZ).isoformat(), **plan})
