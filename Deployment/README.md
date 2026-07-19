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

The frontend is intentionally thin. It calls the backend API, lets the user switch between bike and dock availability, and renders the selected forecast hour on a Leaflet/OpenStreetMap map plus a station table.

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

The map uses Leaflet with OpenStreetMap tiles, so no map API token is required.

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
