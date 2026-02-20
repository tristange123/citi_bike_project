import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from catboost import CatBoostRegressor
import json
import requests
import holidays
from zoneinfo import ZoneInfo
import pydeck as pdk
from pathlib import Path


BASE_DIR = Path(__file__).parent

STATIONS_CSV = BASE_DIR / "citibike-stations.csv"
STATIONS_JSON = BASE_DIR / "true_valid_stations_list.json"
MODEL_PATH = BASE_DIR / "Working_model.cbm"

st.set_page_config(layout="wide")

col1, col2 = st.columns([3, 1])
with col1:
    st.title("🚲 Station Capacity Forecast")
with col2:
    display_mode = st.radio("Display Mode:", ["Bikes", "Docks"], horizontal=True)

# Load station metadata
@st.cache_data
def load_station_info():
    stations_df = pd.read_csv(STATIONS_CSV)
    shortname_to_lat = dict(zip(stations_df['short_name'], stations_df['lat']))
    shortname_to_lon = dict(zip(stations_df['short_name'], stations_df['lon']))
    shortname_to_name = dict(zip(stations_df['short_name'], stations_df['name']))
    with open(STATIONS_JSON, 'r') as f:
        shortnames = json.load(f)
    return set(shortnames), shortname_to_lat, shortname_to_lon, shortname_to_name

shortnames, shortname_to_lat, shortname_to_lon, shortname_to_name = load_station_info()

CITIBIKE_STATUS_URL = "https://gbfs.citibikenyc.com/gbfs/en/station_status.json"
CITIBIKE_INFO_URL = "https://gbfs.citibikenyc.com/gbfs/en/station_information.json"

@st.cache_resource
def load_model():
    model = CatBoostRegressor()
    model.load_model(MODEL_PATH)
    return model

model = load_model()


@st.cache_data(ttl=300) # Cache for 5 minutes

def pull_data():
    status_resp = requests.get(CITIBIKE_STATUS_URL)
    info_resp = requests.get(CITIBIKE_INFO_URL)

    status_data = status_resp.json()["data"]["stations"]
    info_data = info_resp.json()["data"]["stations"]


    df_status = pd.DataFrame(status_data)
    df_info = pd.DataFrame(info_data)


    df = df_status.merge(df_info, on="station_id")

    df = df[df["short_name"].isin(shortnames)].copy()

    # Select useful columns
    df = df[[
        "station_id",
        "short_name",
        "name",
        "num_bikes_available",
        "num_docks_available",
        "lat",
        "lon",
        "last_reported"
    ]]

    df['percentage_available'] = df['num_bikes_available'] / (df['num_bikes_available'] + df['num_docks_available'])
    df['shortname'] = df['short_name']
    df = df.drop('short_name', axis = 1)
    

    return df



def add_Xfeatures(df):
    df['Month'] = df['timestamp'].dt.month
    df['Day'] = df['timestamp'].dt.dayofweek
    df['Hour'] = df['timestamp'].dt.hour
    df['IsWeekend'] = df['Day'].isin([5,6]).astype(int)
    df['minute'] = df['timestamp'].dt.minute
    df['IsRushHour'] = ((df['Hour'].isin([7,8,9,16,17,18])) & (df['IsWeekend'] == 0)).astype(int)
    df['lat'] = df['shortname'].map(shortname_to_lat)
    df['lon'] = df['shortname'].map(shortname_to_lon)

    ny_holidays = holidays.US(state='NY')
    holiday_date_list = list(ny_holidays.keys())

    df['IsHoliday'] = df['timestamp'].dt.date.isin(holiday_date_list).astype(int)
    df['IsNonWorkingDay'] = ((df['IsWeekend'] == 1) | (df['IsHoliday'] == 1)).astype(int)
    

    return df

# -------------------------------------------------
# PREDICTION LOGIC
# -------------------------------------------------
@st.cache_data(ttl=600) # Cache predictions for 10 minutes
def get_all_predictions():

    curr = datetime.now(tz = ZoneInfo('UTC'))
    end = curr + timedelta(days = 7)


    timestamps = []

    # construct column of predictions times for dataframe for predictions
    while (curr < end):
        timestamps.append(curr)
        curr += timedelta(hours = 1)

    timestamp_df = pd.DataFrame({'timestamp': timestamps})

    predictions = {}

    # prepare the data for prediction for each station
    for shortname in shortnames:
        pred_df = timestamp_df.copy()
        pred_df['shortname'] = shortname
        pred_df = add_Xfeatures(pred_df)
        predictions[shortname] = pred_df

    # make predictions
    for name, data in predictions.items():
        x = data.drop('timestamp', axis = 1)
        data['predictions'] = model.predict(x)

    curr_df = pull_data()

    curr_capacities = dict(zip(curr_df['shortname'], curr_df['percentage_available']))

    # predictions - mean_offset * (1 - (prediction time  - current time) / 1440))
    # adjusted predicted capacity of at each time based on the current capacity by providing a mean adjustment to the xgboost curve
    # this mean adjustment decays in importance as predictions getting further away from the present

    for name, data in predictions.items():
        data['initial_offset'] = data.loc[0, 'predictions'] - curr_capacities[name]
        data['updated_predictions'] = data['predictions'] - (data['initial_offset'] * np.clip((1 - ((data['timestamp'] - datetime.now(ZoneInfo("UTC"))).dt.total_seconds() / 86400)), 0, 1))
        data['updated_predictions'] = data['updated_predictions'].clip(lower = 0, upper = 1)

    timestamps = [x.astimezone(ZoneInfo("America/New_York")) for x in timestamps]

    return predictions, timestamps


predictions_dict, timestamps = get_all_predictions()

selected_time = st.slider(
    "Select prediction time:",
    min_value=timestamps[0],
    max_value=timestamps[-1],
    value=timestamps[0],
    step=timedelta(hours=1),
    format="MM/DD/YYYY - hh:mm A"
)

# Prepare data for the map for the selected time
map_data = []
for shortname, df in predictions_dict.items():
    prediction_row = df[df['timestamp'] == selected_time]
    
    if not prediction_row.empty:
        capacity = prediction_row['updated_predictions'].iloc[0]
        map_data.append({
            'shortname': shortname,
            'lat': shortname_to_lat.get(shortname),
            'lon': shortname_to_lon.get(shortname),
            'name': shortname_to_name.get(shortname, shortname),
            'predicted_capacity': capacity,
            'predicted_dock_capacity': 1 - capacity
        })

map_df = pd.DataFrame(map_data).dropna(subset=['lat', 'lon'])

if display_mode == "Bikes":
    map_df['display_val'] = map_df['predicted_capacity']
    tooltip_html = "<b>{name}</b><br/>Predicted Bike Availability: {predicted_capacity:.0%}"
    point_color = [200, 30, 0, 160] # Red for bikes
    df_col = 'predicted_capacity'
    df_label = 'Predicted Bike Availability'
else:
    map_df['display_val'] = map_df['predicted_dock_capacity']
    tooltip_html = "<b>{name}</b><br/>Predicted Dock Availability: {predicted_dock_capacity:.0%}"
    point_color = [30, 100, 200, 160] # Blue for docks
    df_col = 'predicted_dock_capacity'
    df_label = 'Predicted Dock Availability'

map_df['radius'] = map_df['display_val'] * 70 + 25

st.pydeck_chart(pdk.Deck(
    map_style='mapbox://styles/mapbox/streets-v11',
    initial_view_state=pdk.ViewState(
        latitude=map_df["lat"].mean(),
        longitude=map_df["lon"].mean(),
        zoom=12,
        pitch=50,
    ),
    layers=[
        pdk.Layer(
            "ScatterplotLayer",
            data=map_df,
            get_position="[lon, lat]",
            get_color=point_color,
            get_radius="radius", # Base size + capacity scaling
            pickable=True,
        ),
    ],
    tooltip={"html": tooltip_html}
))

st.write("Current time:", datetime.now(ZoneInfo("US/Eastern")).strftime("%A, %B %d, %Y %I:%M %p"))
st.write(f"Showing predictions for: {selected_time.strftime('%A, %B %d, %Y %I:%M %p')}")

# Display a table with the data
st.dataframe(map_df[['name', df_col]].rename(columns={'name': 'Station Name', df_col: df_label}).sort_values('Station Name').set_index('Station Name'))
