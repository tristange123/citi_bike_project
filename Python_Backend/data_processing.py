import pandas as pd
from zoneinfo import ZoneInfo
from datetime import datetime as dt
def process_file(csv_file):
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


    df = read_csv(csv_file)

    correct_ids = set()
    for sid in df['station_id'].unique():
        if len(sid) <= 4:
            correct_ids.add(sid)


    mask = (
        df['station_id'].isin(correct_ids) & 
        (df['station_status_last_reported'] < dt(2018, 12, 31, tzinfo=ZoneInfo('America/New_York'))) & 
        (df['station_status_last_reported'] > dt(2018, 1, 1, tzinfo=ZoneInfo('America/New_York')))
    )


    cols = ['station_id', 'num_bikes_available', 'num_docks_available', 'station_status_last_reported']

    df = df.loc[mask, cols].copy()

    return df

dataframes = []

file_names = {'citi_bike_data_00000.csv', 'citi_bike_data_00001.csv'}
for file in file_names:
    df = process_file(file)
    dataframes.append(df)
    print(f"Processed {file}.")

final_df = pd.concat(dataframes, ignore_index=True)

final_df.to_csv('processed_citi_bike_data.csv', index=False)