import meteostat as ms
import pandas as pd
from datetime import datetime as dt, timezone, timedelta

manhattan = ms.Point(40.78, -73.96)

start = dt(2017, 1, 1)
end = dt(2020, 1, 1) 

stations = ms.stations.nearby(manhattan, limit=4)


print("Fetching data... this may take a moment.")
data = ms.hourly(stations, start, end)
df_weather = data.fetch()

df_weather = df_weather.groupby('time').mean()

df_weather = df_weather.reset_index()
df_weather['time'] = df_weather['time'].dt.tz_localize('UTC')
df_weather = df_weather[['time', 'temp','prcp','snwd','wspd']]
df_weather = df_weather.fillna(0)

df_weather.to_parquet('All_Data/Weather_Data/weather_data.parquet')