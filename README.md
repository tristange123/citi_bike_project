# Citi Bike Availability Forecast

A full-stack web app for forecasting Citi Bike station bike and dock availability in NYC.

The current deployment is built as a small production-style web system: a FastAPI backend loads a trained CatBoost model, pulls live Citi Bike GBFS station data, serves prediction JSON through one API route, and a Next.js frontend renders an interactive station map and forecast table.

## Deployment: 
https://citibikecapacitypredictor.vercel.app/

## Architecture

```text
model_testing.ipynb          # Jupyter Notebook for building the Cat Boost model
Deployment/
├── backend/                 # FastAPI prediction API
├── frontend/                # Next.js dashboard
├── Models/baseline.cbm      # CatBoost model used by the API
├── citibike-stations.csv    # Station metadata
├── true_valid_stations_list.json
└── requirements.txt         # Backend Python dependencies
```

Runtime flow:

1. The backend receives `GET /api/predictions`.
2. It pulls live Citi Bike station status and station metadata from the public GBFS API.
3. It builds the same time/station/location features used by the deployed model.
4. It runs the CatBoost model for 7 days of hourly forecasts.
5. It adjusts near-term predictions toward current live station capacity, with the adjustment decaying over time.
6. The frontend consumes that JSON and displays station-level bike/dock availability on a Leaflet map and table.

## Software Features

- **FastAPI backend:** typed API service with one prediction endpoint and CORS configuration for the frontend.
- **Next.js frontend:** single-page dashboard with loading/error states, time slider, Bikes/Docks toggle, and station table.
- **Interactive map:** Leaflet with OpenStreetMap tiles, so no Mapbox token or paid map provider is required.
- **Live data integration:** pulls current station state from Citi Bike GBFS endpoints at request time.
- **Model serving layer:** isolates model loading, feature creation, live-data adjustment, and JSON response formatting.
- **Deployable split architecture:** backend and frontend can be deployed independently, which matches common production hosting setups.

## Tech Stack

- **Backend:** Python, FastAPI, Uvicorn, Pandas, NumPy, CatBoost
- **Frontend:** Next.js, React, TypeScript, Leaflet
- **Data source:** Citi Bike GBFS public API
- **Model artifact:** CatBoost `.cbm` model stored in `Deployment/Models/`
- **Deployment:** Vercel

