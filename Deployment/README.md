# Citi Bike Deployment

This folder contains the production-facing application code for the Citi Bike forecast project.

The deployment is split into:

- `backend/`: FastAPI service that loads the CatBoost model and serves predictions.
- `frontend/`: Next.js single-page dashboard that displays the forecast map and table.

The backend keeps using these existing deployment assets:

- `Models/baseline.cbm`
- `citibike-stations.csv`
- `true_valid_stations_list.json`

## Runtime Architecture

The backend owns model serving and live-data integration. It pulls current Citi Bike station data from GBFS, builds prediction features, runs the CatBoost model, adjusts near-term forecasts toward current station capacity, and returns frontend-ready JSON.

The frontend is intentionally thin. It calls the backend API, lets the user switch between bike and dock availability, and renders the selected forecast hour on a Leaflet map (CARTO Positron basemap) plus a station table.

## Backend

From `Deployment/`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Prediction data is served from:

```text
GET http://localhost:8000/api/predictions
```

Route planning (the Navigate view) is served from:

```text
GET http://localhost:8000/api/route?from=40.7644,-73.9737&to=40.7046,-74.0136[&depart=2026-10-24T08:00]
```

It returns up to three walk → bike → walk options (`fastest`, `most reliable`, `alternate`) plus a `walk only` baseline, and `recommendedIndex` points at the lowest expected time. How it works:

- **Candidates:** the 5 nearest stations with bikes around the start pin and with docks around the destination pin (800 m radius, widened up to 3.2 km).
- **Travel times** (`backend/travel.py`): straight-line distance × 1.3 detour factor, at 1.4 m/s walking and 4.2 m/s biking, plus 60 s each to unlock and dock. There is no routing engine, so trips that cross rivers or go around parks come out optimistic.
- **Availability:** live GBFS counts within 10 minutes. Further out, stations the model covers use the CatBoost forecast (fraction × live capacity); other stations use live counts discounted by 40%.
- **Scoring** (`backend/planner.py`): travel time plus the chance a bike or dock is missing (`1 − e^(−expected count)`) times the walk to the next-nearest station.

Run the backend tests from `Deployment/`:

```bash
python -m unittest discover -s tests -t .
```

Optional environment variables:

- `CITIBIKE_MODEL_NAME`: model filename inside `Models/`, defaulting to `baseline.cbm`.
- `CORS_ORIGINS`: comma-separated frontend origins, defaulting to `http://localhost:3000`.

## Frontend

From `Deployment/frontend/`:

```bash
npm install
cp .env.local.example .env.local
npm run dev
```

The map uses Leaflet with CARTO Positron tiles, which need a free key from https://carto.com/basemaps/apikey set as `NEXT_PUBLIC_CARTO_API_KEY` (in `.env.local` locally and in Vercel environment variables in production). Without a key it falls back to standard OpenStreetMap tiles.

The frontend reads the backend URL from:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

## Production Deployment

Deploy the backend and frontend as separate services.

### Backend On Render

Create a Render Web Service with:

- **Root directory:** `Deployment`
- **Runtime:** Python
- **Build command:** `pip install -r requirements.txt`
- **Start command:** `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`

Set environment variables:

```bash
CITIBIKE_MODEL_NAME=baseline.cbm
CORS_ORIGINS=*
```

For a stricter production setup, replace `*` with your exact frontend URL:

```bash
CORS_ORIGINS=https://your-frontend-domain.vercel.app
```

After deploy, verify:

```text
https://your-backend-domain.onrender.com/api/predictions
```

### Frontend On Vercel

Create a Vercel project with:

- **Root directory:** `Deployment/frontend`
- **Framework preset:** Next.js
- **Install command:** `npm install`
- **Build command:** `npm run build`
- **Output directory:** leave blank, or use `.next` if Vercel requires a value

Set environment variables:

```bash
NEXT_PUBLIC_API_BASE_URL=https://your-backend-domain.onrender.com
```

After the frontend deploys, update the backend `CORS_ORIGINS` value to the final Vercel URL.

### Backend On A VPS

```bash
git clone <repo-url>
cd Citi_Bike_Revival/Deployment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
CORS_ORIGINS=https://your-frontend-domain.com \
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

For a durable VPS deployment, run Uvicorn under `systemd` or Docker and put Nginx/Caddy in front of it for HTTPS and reverse proxying.
