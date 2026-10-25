import json
import os
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import holidays
import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from zoneinfo import ZoneInfo

from .gbfs_cache import fetch_station_frame

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

# Within this horizon live GBFS counts beat the model, so they are used as-is.
LIVE_HORIZON_SECONDS = 10 * 60
# Stations the model does not cover only have live counts, which go stale with time.
UNMODELED_COUNT_FACTOR = 0.6


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
    df = fetch_station_frame()
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


@lru_cache(maxsize=4)
def load_holiday_dates(years: tuple[int, ...]) -> list:
    # holidays.US is lazily populated, so years must be passed explicitly or keys() is empty.
    return list(holidays.US(state="NY", years=years).keys())


def add_prediction_features(df: pd.DataFrame, station_meta: dict[str, dict[str, Any]]) -> pd.DataFrame:
    df["Month"] = df["timestamp"].dt.month
    df["Day"] = df["timestamp"].dt.dayofweek
    df["Hour"] = df["timestamp"].dt.hour
    df["IsWeekend"] = df["Day"].isin([5, 6]).astype(int)
    df["minute"] = df["timestamp"].dt.minute
    df["IsRushHour"] = (
        df["Hour"].isin([7, 8, 9, 16, 17, 18]) & (df["IsWeekend"] == 0)
    ).astype(int)
    df["lat"] = df["shortname"].map({shortname: meta["lat"] for shortname, meta in station_meta.items()})
    df["lon"] = df["shortname"].map({shortname: meta["lon"] for shortname, meta in station_meta.items()})

    years = tuple(sorted(int(year) for year in df["timestamp"].dt.year.unique()))
    df["IsHoliday"] = df["timestamp"].dt.date.isin(load_holiday_dates(years)).astype(int)
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


def predict_raw(pred_df: pd.DataFrame) -> np.ndarray:
    """Raw model bike fraction for each (shortname, timestamp) row of pred_df."""
    _, station_meta = load_station_info()
    pred_df = add_prediction_features(pred_df, station_meta)
    return load_model().predict(pred_df[FEATURE_COLUMNS])


def apply_live_offset(raw, raw_now, live_fraction, seconds_ahead):
    """Shift forecasts toward live capacity, decaying linearly to zero over 24 hours.

    All arguments broadcast elementwise. A NaN live_fraction leaves the raw forecast untouched.
    """
    offsets = np.where(np.isnan(live_fraction), 0.0, raw_now - live_fraction)
    decay = np.clip(1 - np.asarray(seconds_ahead) / 86400, 0, 1)
    return np.clip(raw - offsets * decay, 0, 1)


def predict_at(
    shortnames: list[str],
    timestamps: list[datetime],
    live_fraction: np.ndarray,
    now_utc: datetime,
) -> np.ndarray:
    """Live-adjusted bike fraction for each (shortnames[i], timestamps[i]) pair."""
    unique_shortnames = sorted(set(shortnames))
    rows = pd.DataFrame(
        {
            "shortname": list(shortnames) + unique_shortnames,
            "timestamp": pd.DatetimeIndex(list(timestamps) + [now_utc] * len(unique_shortnames)),
        }
    )
    raw = predict_raw(rows)
    raw_targets = raw[: len(shortnames)]
    raw_now_by_station = dict(zip(unique_shortnames, raw[len(shortnames):]))
    raw_now = np.array([raw_now_by_station[shortname] for shortname in shortnames])
    seconds_ahead = np.array([(timestamp - now_utc).total_seconds() for timestamp in timestamps])
    return apply_live_offset(raw_targets, raw_now, np.asarray(live_fraction, dtype=float), seconds_ahead)


def predict_counts(
    network: pd.DataFrame,
    station_idx: np.ndarray,
    kinds: np.ndarray,
    timestamps: list[datetime],
    now_utc: datetime,
) -> np.ndarray:
    """Expected bikes (kind "bikes") or docks (kind "docks") at network rows station_idx at timestamps.

    Near-term or unmodeled queries use live counts; modeled stations further out use the forecast,
    converted from a fraction to a count with the station's live bikes + docks as capacity.
    """
    station_idx = np.asarray(station_idx)
    kinds = np.asarray(kinds)
    bikes = network["bikes"].to_numpy(dtype=float)[station_idx]
    docks = network["docks"].to_numpy(dtype=float)[station_idx]
    modeled = network["modeled"].to_numpy(dtype=bool)[station_idx]
    is_bikes = kinds == "bikes"

    counts = np.where(is_bikes, bikes, docks)
    seconds_ahead = np.array([(timestamp - now_utc).total_seconds() for timestamp in timestamps])
    future = seconds_ahead > LIVE_HORIZON_SECONDS

    use_model = future & modeled
    if use_model.any():
        capacity = bikes + docks
        live_fraction = np.where(capacity > 0, bikes / np.maximum(capacity, 1), np.nan)
        shortnames = network["shortname"].to_numpy()[station_idx]
        fraction = predict_at(
            list(shortnames[use_model]),
            [timestamp for timestamp, flag in zip(timestamps, use_model) if flag],
            live_fraction[use_model],
            now_utc,
        )
        predicted_bikes = fraction * capacity[use_model]
        counts[use_model] = np.where(
            is_bikes[use_model], predicted_bikes, capacity[use_model] - predicted_bikes
        )

    counts[future & ~modeled] *= UNMODELED_COUNT_FACTOR
    return counts
