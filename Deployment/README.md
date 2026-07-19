# Citi Bike Deployment

This deployment is split into:

- `backend/`: FastAPI service that loads the CatBoost model and serves predictions.
- `frontend/`: Next.js single-page dashboard that displays the forecast map and table.

The backend keeps using these existing deployment assets:

- `Models/baseline.cbm`
- `citibike-stations.csv`
- `true_valid_stations_list.json`

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

Set `NEXT_PUBLIC_MAPBOX_TOKEN` in `.env.local` to render the interactive map.
