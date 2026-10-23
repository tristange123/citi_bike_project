import threading
import time

import pandas as pd
import requests
from fastapi import HTTPException


CITIBIKE_STATUS_URL = "https://gbfs.citibikenyc.com/gbfs/en/station_status.json"
CITIBIKE_INFO_URL = "https://gbfs.citibikenyc.com/gbfs/en/station_information.json"

# GBFS feeds advertise a 60 second ttl, so refetching more often gains nothing.
CACHE_TTL_SECONDS = 60

_lock = threading.Lock()
_cached_frame: pd.DataFrame | None = None
_cached_at = 0.0


def fetch_station_frame() -> pd.DataFrame:
    """Return station_status merged with station_information, cached for CACHE_TTL_SECONDS."""
    global _cached_frame, _cached_at

    with _lock:
        if _cached_frame is not None and time.monotonic() - _cached_at < CACHE_TTL_SECONDS:
            return _cached_frame.copy()

        try:
            status_resp = requests.get(CITIBIKE_STATUS_URL, timeout=15)
            info_resp = requests.get(CITIBIKE_INFO_URL, timeout=15)
            status_resp.raise_for_status()
            info_resp.raise_for_status()
        except requests.RequestException as exc:
            raise HTTPException(status_code=502, detail="Failed to pull live Citi Bike data") from exc

        df_status = pd.DataFrame(status_resp.json()["data"]["stations"])
        df_info = pd.DataFrame(info_resp.json()["data"]["stations"])
        df = df_status.merge(df_info, on="station_id")
        df["short_name"] = df["short_name"].astype(str)

        _cached_frame = df
        _cached_at = time.monotonic()
        return df.copy()


def load_network(modeled_shortnames: set[str]) -> pd.DataFrame:
    """All installed stations with live counts, flagged by whether the forecast model covers them."""
    df = fetch_station_frame()
    df = df[df["is_installed"] == 1].copy()

    # A station that is not renting has no usable bikes; one that is not returning has no usable docks.
    df["bikes"] = df["num_bikes_available"].where(df["is_renting"] == 1, 0).astype(int)
    df["docks"] = df["num_docks_available"].where(df["is_returning"] == 1, 0).astype(int)
    ebikes = df["num_ebikes_available"] if "num_ebikes_available" in df else 0
    df["ebikes"] = pd.Series(ebikes, index=df.index).fillna(0).astype(int).where(df["is_renting"] == 1, 0)
    df["modeled"] = df["short_name"].isin(modeled_shortnames)

    return (
        df.rename(columns={"short_name": "shortname"})[
            ["shortname", "name", "lat", "lon", "bikes", "ebikes", "docks", "modeled"]
        ]
        .reset_index(drop=True)
    )
