import pandas as pd
from zoneinfo import ZoneInfo
from datetime import datetime as dt
import json

STARTTIME = dt(2019, 1, 1, tzinfo=ZoneInfo('America/New_York'))
ENDTIME = dt(2019, 12, 31, tzinfo=ZoneInfo('America/New_York'))
SPARCITY = 1
INPUT_FILES = ['citi_bike_data_00000.csv','citi_bike_data_00001.csv']
OUTPUT_FILE = 'medium_crossval_set.csv'
VALIDATION_SET = True




stations_df = pd.read_csv('citibike-stations.csv')

id_to_shortname = dict(zip(stations_df['station_id'], stations_df['short_name']))

def read_csv(filename: str) -> pd.DataFrame:
    """
    Read DataFrame from a CSV file ``filename`` and convert to a 
    preferred schema.
    """
    df = pd.read_csv(
        filename,
        sep=",",
        na_values="\\N",
        dtype={
            "station_id": str,
            # Use Pandas Int16 dtype to allow for nullable integers
            "num_bikes_available": "Int16",
            "num_ebikes_available": "Int16",
            "num_bikes_disabled": "Int16",
            "num_docks_available": "Int16",
            "num_docks_disabled": "Int16",
            "is_installed": "Int16",
            "is_renting": "Int16",
            "is_returning": "Int16",
            "station_status_last_reported": "Int64",
            "station_name": str,
            "lat": float,
            "lon": float,
            "region_id": str,
            "capacity": "Int16",
            # Use pandas boolean dtype to allow for nullable booleans
            "has_kiosk": "boolean",
            "station_information_last_updated": "Int64",
            "missing_station_information": "boolean"
        },
        nrows = 1000000
    )
    # Read in timestamps as UNIX/POSIX epochs but then convert to the local
    # bike share timezone.
    df["station_status_last_reported"] = pd.to_datetime(
        df["station_status_last_reported"], unit="s", origin="unix", utc=True
    ).dt.tz_convert("America/New_York")

    df["station_information_last_updated"] = pd.to_datetime(
        df["station_information_last_updated"], unit="s", origin="unix", utc=True
    ).dt.tz_convert("America/New_York")

    return df

def process_file(csv_file):
    df = read_csv(csv_file)

    correct_ids = set()
    for sid in df['station_id'].unique():
        if len(sid) <= 4:
            correct_ids.add(sid)


    mask = (
        df['station_id'].isin(correct_ids) & 
        (df['station_status_last_reported'] < ENDTIME) & 
        (df['station_status_last_reported'] > STARTTIME)
    )


    cols = ['station_id', 'num_bikes_available', 'num_docks_available', 'station_status_last_reported']

    df = df.loc[mask, cols].iloc[::SPARCITY].copy()

    # Add stations with valid Legacy ID -> shortnames into the working station list

    

    
    with open('valid_stations_list.json', 'r') as f:
        valid_stations_list = json.load(f)
    
    valid_stations_set = set(valid_stations_list)


    if not VALIDATION_SET:
        for id in df['station_id'].unique():
            if int(id) in id_to_shortname.keys():
                valid_stations_set.add(id)
        
            else:
                print(f"Station ID {id} not found in station information. Skipping.")

        with open('valid_stations_list.json', 'w') as f:
            json.dump(list(valid_stations_set), f)

    df = df[df['station_id'].isin(valid_stations_set)].copy()

    return df

dataframes = []

for file in INPUT_FILES:
    df = process_file(file)
    dataframes.append(df)
    print(f"Processed {file}.")

final_df = pd.concat(dataframes, ignore_index=True)

final_df.to_csv(OUTPUT_FILE, index=False)