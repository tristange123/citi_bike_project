# Citi Bike Availability Forecast

A full-stack web app for forecasting Citi Bike station bike and dock availability in NYC.

The current deployment is built as a small production-style web system: a FastAPI backend loads a trained CatBoost model, pulls live Citi Bike GBFS station data, serves prediction JSON through one API route, and a Next.js frontend renders an interactive station map and forecast table.

## Architecture

```text
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

## Local Development

### Backend

```bash
cd Deployment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

The API will be available at:

```text
http://localhost:8000/api/predictions
```

Useful backend environment variables:

```bash
export CITIBIKE_MODEL_NAME=baseline.cbm
export CORS_ORIGINS=http://localhost:3000
```

### Frontend

```bash
cd Deployment/frontend
npm install
cp .env.local.example .env.local
npm run dev
```

The dashboard will be available at:

```text
http://localhost:3000
```

For local development, `.env.local` should contain:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

## Deployment

The easiest production setup is to deploy the backend and frontend separately.

### Backend On Render

1. Push the repository to GitHub.
2. Create a new Render **Web Service**.
3. Set the root directory to `Deployment`.
4. Use Python as the runtime.
5. Set the build command:

```bash
pip install -r requirements.txt
```

6. Set the start command:

```bash
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

7. Add environment variables:

```bash
CITIBIKE_MODEL_NAME=baseline.cbm
CORS_ORIGINS=https://your-frontend-domain.vercel.app
```

8. Deploy and copy the backend URL. It should serve:

```text
https://your-backend-domain.onrender.com/api/predictions
```

### Frontend On Vercel

1. Import the GitHub repository into Vercel.
2. Set the root directory to `Deployment/frontend`.
3. Keep the default Next.js build settings:

```bash
npm install
npm run build
```

4. In Vercel project settings, make sure **Output Directory** is blank. If Vercel requires a value, use `.next`. Do not use `public`; this is not a static HTML export.
5. Add this environment variable:

```bash
NEXT_PUBLIC_API_BASE_URL=https://your-backend-domain.onrender.com
```

6. Deploy the Vercel app.
7. Update the backend `CORS_ORIGINS` value to the final Vercel domain if it changed.

### Backend On A VPS

From the server:

```bash
git clone <repo-url>
cd Citi_Bike_Revival/Deployment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
CORS_ORIGINS=https://your-frontend-domain.com \
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

For a real VPS deployment, put Nginx or Caddy in front of Uvicorn, terminate HTTPS there, and run the Uvicorn command under `systemd`, `supervisor`, or Docker.

## API Contract

```text
GET /api/predictions
```

Returns:

- `generatedAt`: timestamp for the prediction response
- `forecastStart` / `forecastEnd`: forecast window
- `stations`: station metadata plus hourly prediction points
- each prediction includes `bikeAvailability` and `dockAvailability` as values from `0` to `1`

## Notes

The data science work is still an important part of the project, but the deployable app is now organized around the software system that serves and visualizes the model. Older exploratory notebooks and training data are separate from the production path in `Deployment/`.