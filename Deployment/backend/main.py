import os
import json
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import holidays
import numpy as np
import pandas as pd
import requests
from catboost import CatBoostRegressor
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from zoneinfo import ZoneInfo


BASE_DIR = Path(__file__).resolve().parents[1]
STATIONS_CSV = BASE_DIR / "citibike-stations.csv"
STATIONS_JSON = BASE_DIR / "true_valid_stations_list.json"
MODEL_PATH = BASE_DIR / "Models" / os.getenv("CITIBIKE_MODEL_NAME", "baseline.cbm")

CITIBIKE_STATUS_URL = "https://gbfs.citibikenyc.com/gbfs/en/station_status.json"
CITIBIKE_INFO_URL = "https://gbfs.citibikenyc.com/gbfs/en/station_information.json"
NY_TZ = ZoneInfo("America/New_York")
UTC_TZ = ZoneInfo("UTC")

FEATURE_COLUMNS = [
    "shortname",
    "Month",
    "Day",
    "Hour",
    "IsWeekend",
    "IsHoliday",
    "IsNonWorkingDay",
    "lat",
    "lon",
    "IsRushHour",
    "minute",
]


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


@lru_cache(maxsize=1)
def load_station_info() -> tuple[set[str], dict[str, dict[str, Any]]]:
    stations_df = pd.read_csv(STATIONS_CSV, dtype={"short_name": str})
    with open(STATIONS_JSON, "r", encoding="utf-8") as file:
        shortnames = {str(shortname) for shortname in json.load(file)}

    stations_df = stations_df[stations_df["short_name"].isin(shortnames)].copy()
    station_meta = {
        row["short_name"]: {
            "name": row["name"],
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
        }
        for row in stations_df.to_dict(orient="records")
    }
    return shortnames, station_meta


@lru_cache(maxsize=1)
def load_model() -> CatBoostRegressor:
    if not MODEL_PATH.exists():
        raise RuntimeError(f"Model file not found: {MODEL_PATH}")

    model = CatBoostRegressor()
    model.load_model(MODEL_PATH)
    return model


def pull_live_station_data(shortnames: set[str]) -> pd.DataFrame:
    try:
        status_resp = requests.get(CITIBIKE_STATUS_URL, timeout=15)
        info_resp = requests.get(CITIBIKE_INFO_URL, timeout=15)
        status_resp.raise_for_status()
        info_resp.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail="Failed to pull live Citi Bike data") from exc

    status_data = status_resp.json()["data"]["stations"]
    info_data = info_resp.json()["data"]["stations"]

    df_status = pd.DataFrame(status_data)
    df_info = pd.DataFrame(info_data)
    df = df_status.merge(df_info, on="station_id")
    df["short_name"] = df["short_name"].astype(str)
    df = df[df["short_name"].isin(shortnames)].copy()

    df = df[
        [
            "station_id",
            "short_name",
            "name",
            "num_bikes_available",
            "num_docks_available",
            "lat",
            "lon",
            "last_reported",
        ]
    ]
    total_capacity = df["num_bikes_available"] + df["num_docks_available"]
    df["percentage_available"] = np.where(
        total_capacity > 0,
        df["num_bikes_available"] / total_capacity,
        0,
    )
    df["shortname"] = df["short_name"]
    return df.drop(columns=["short_name"])


def add_prediction_features(df: pd.DataFrame, station_meta: dict[str, dict[str, Any]]) -> pd.DataFrame:
    df["Month"] = df["timestamp"].dt.month
    df["Day"] = df["timestamp"].dt.dayofweek
    df["Hour"] = df["timestamp"].dt.hour
    df["IsWeekend"] = df["Day"].isin([5, 6]).astype(int)
    df["minute"] = df["timestamp"].dt.minute
    df["IsRushHour"] = (
        df["Hour"].isin([7, 8, 9, 16, 17, 18]) & (df["IsWeekend"] == 0)
    ).astype(int)
    df["lat"] = df["shortname"].map(lambda shortname: station_meta[shortname]["lat"])
    df["lon"] = df["shortname"].map(lambda shortname: station_meta[shortname]["lon"])

    ny_holidays = holidays.US(state="NY")
    holiday_dates = set(ny_holidays.keys())
    df["IsHoliday"] = df["timestamp"].dt.date.isin(holiday_dates).astype(int)
    df["IsNonWorkingDay"] = ((df["IsWeekend"] == 1) | (df["IsHoliday"] == 1)).astype(int)
    return df


def build_forecast_timestamps() -> list[datetime]:
    current_time = datetime.now(tz=UTC_TZ)
    end_time = current_time + timedelta(days=7)

    timestamps: list[datetime] = []
    while current_time < end_time:
        timestamps.append(current_time)
        current_time += timedelta(hours=1)

    return timestamps


@app.get("/api/predictions", response_model=PredictionResponse)
def get_predictions() -> PredictionResponse:
    shortnames, station_meta = load_station_info()
    live_df = pull_live_station_data(shortnames)
    model = load_model()

    timestamps = build_forecast_timestamps()
    timestamp_df = pd.DataFrame({"timestamp": timestamps})
    current_capacities = dict(zip(live_df["shortname"], live_df["percentage_available"]))
    current_bikes = dict(zip(live_df["shortname"], live_df["num_bikes_available"]))
    current_docks = dict(zip(live_df["shortname"], live_df["num_docks_available"]))
    now_utc = datetime.now(tz=UTC_TZ)

    stations: list[StationPrediction] = []
    for shortname in sorted(shortnames):
        if shortname not in station_meta:
            continue

        pred_df = timestamp_df.copy()
        pred_df["shortname"] = shortname
        pred_df = add_prediction_features(pred_df, station_meta)
        pred_df["predictions"] = model.predict(pred_df[FEATURE_COLUMNS])

        current_capacity = current_capacities.get(shortname)
        if current_capacity is not None:
            initial_offset = pred_df.loc[0, "predictions"] - current_capacity
            decay = np.clip(
                1 - ((pred_df["timestamp"] - now_utc).dt.total_seconds() / 86400),
                0,
                1,
            )
            pred_df["updated_predictions"] = pred_df["predictions"] - (initial_offset * decay)
        else:
            pred_df["updated_predictions"] = pred_df["predictions"]

        pred_df["updated_predictions"] = pred_df["updated_predictions"].clip(lower=0, upper=1)

        predictions = [
            PredictionPoint(
                timestamp=row.timestamp.astimezone(NY_TZ).isoformat(),
                bikeAvailability=round(float(row.updated_predictions), 4),
                dockAvailability=round(1 - float(row.updated_predictions), 4),
            )
            for row in pred_df.itertuples(index=False)
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
