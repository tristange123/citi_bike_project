import pandas as pd
from zoneinfo import ZoneInfo
from datetime import datetime as dt
import json

STARTTIME = dt(2019, 1, 1, tzinfo=ZoneInfo('America/New_York'))
ENDTIME = dt(2019, 12, 31, tzinfo=ZoneInfo('America/New_York'))
SPARCITY = 1   
INPUT_FILES = []
for i in range(0,50):
    INPUT_FILES.append(f"data/citi_bike_data_{i:05d}.csv")
OUTPUT_FILE = 'smallvalset_14thstbelow.csv'
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
        nrows = 10000

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

    valid_pos_ints_mask = df['station_id'].astype(str).str.isdigit()

    df = df[valid_pos_ints_mask].copy()

    df['station_id'] = df['station_id'].astype('int64')
    
    mask = (
        df['station_id'].isin(id_to_shortname.keys()) & 
        (df['station_status_last_reported'] < ENDTIME) & 
        (df['station_status_last_reported'] > STARTTIME)
    )


    cols = ['station_id', 'num_bikes_available', 'num_docks_available', 'station_status_last_reported']

    df = df.loc[mask, cols].iloc[::SPARCITY].copy()

    

    df['shortname'] = df['station_id'].map(id_to_shortname)

    


    # Add stations with valid Legacy ID -> shortnames into the working station list
    
    with open('valid_stations_list.json', 'r') as f:
        valid_stations_list = json.load(f)
    
    valid_stations_set = set(valid_stations_list)


    if not VALIDATION_SET:
        for shortname in df['shortname'].unique():
           
            valid_stations_set.add(shortname)
        
         

        with open('valid_stations_list.json', 'w') as f:
            json.dump(list(valid_stations_set), f)

    

    df = df[df['shortname'].isin(valid_stations_set)].copy()

    print(df['shortname'].unique())

    return df

dataframes = []

for file in INPUT_FILES:
    df = process_file(file)
    dataframes.append(df)
    print(f"Processed {file}.")

final_df = pd.concat(dataframes, ignore_index=True)

final_df.to_csv(OUTPUT_FILE, index=False)