"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import mapboxgl from "mapbox-gl";

type DisplayMode = "bikes" | "docks";

type PredictionPoint = {
  timestamp: string;
  bikeAvailability: number;
  dockAvailability: number;
};

type StationPrediction = {
  shortname: string;
  name: string;
  lat: number;
  lon: number;
  currentBikeAvailability: number | null;
  currentBikesAvailable: number | null;
  currentDocksAvailable: number | null;
  predictions: PredictionPoint[];
};

type PredictionResponse = {
  generatedAt: string;
  forecastStart: string;
  forecastEnd: string;
  stations: StationPrediction[];
};

const apiBaseUrl = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);
const mapboxToken = process.env.NEXT_PUBLIC_MAPBOX_TOKEN;

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function getAvailability(station: StationPrediction, selectedIndex: number, mode: DisplayMode) {
  const prediction = station.predictions[selectedIndex];
  return mode === "bikes" ? prediction.bikeAvailability : prediction.dockAvailability;
}

export default function Home() {
  const [data, setData] = useState<PredictionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [displayMode, setDisplayMode] = useState<DisplayMode>("bikes");
  const [selectedIndex, setSelectedIndex] = useState(0);

  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const markersRef = useRef<mapboxgl.Marker[]>([]);

  useEffect(() => {
    async function loadPredictions() {
      try {
        setIsLoading(true);
        const response = await fetch(`${apiBaseUrl}/api/predictions`);
        if (!response.ok) {
          throw new Error(`Prediction API returned ${response.status}`);
        }
        setData(await response.json());
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load predictions");
      } finally {
        setIsLoading(false);
      }
    }

    loadPredictions();
  }, []);

  const timestamps = data?.stations[0]?.predictions.map((prediction) => prediction.timestamp) ?? [];
  const selectedTimestamp = timestamps[selectedIndex];

  const tableRows = useMemo(() => {
    if (!data) {
      return [];
    }

    return data.stations
      .map((station) => ({
        ...station,
        displayAvailability: getAvailability(station, selectedIndex, displayMode),
      }))
      .sort((a, b) => b.displayAvailability - a.displayAvailability);
  }, [data, selectedIndex, displayMode]);

  useEffect(() => {
    if (!mapboxToken || !mapContainerRef.current || mapRef.current) {
      return;
    }

    mapboxgl.accessToken = mapboxToken;
    mapRef.current = new mapboxgl.Map({
      container: mapContainerRef.current,
      style: "mapbox://styles/mapbox/light-v11",
      center: [-73.98, 40.73],
      zoom: 12,
      pitch: 35,
    });
    mapRef.current.addControl(new mapboxgl.NavigationControl(), "top-right");

    return () => {
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!data || !mapRef.current) {
      return;
    }

    markersRef.current.forEach((marker) => marker.remove());
    markersRef.current = [];

    const bounds = new mapboxgl.LngLatBounds();
    const color = displayMode === "bikes" ? "rgba(200, 30, 0, 0.72)" : "rgba(30, 100, 200, 0.72)";

    data.stations.forEach((station) => {
      const availability = getAvailability(station, selectedIndex, displayMode);
      const markerElement = document.createElement("div");
      markerElement.className = "station-marker";
      markerElement.style.width = `${availability * 44 + 14}px`;
      markerElement.style.height = `${availability * 44 + 14}px`;
      markerElement.style.background = color;

      const popup = new mapboxgl.Popup({ offset: 16 }).setHTML(
        `<strong>${station.name}</strong><br/>${displayMode === "bikes" ? "Bike" : "Dock"} availability: ${formatPercent(
          availability,
        )}`,
      );

      const marker = new mapboxgl.Marker(markerElement)
        .setLngLat([station.lon, station.lat])
        .setPopup(popup)
        .addTo(mapRef.current!);

      markersRef.current.push(marker);
      bounds.extend([station.lon, station.lat]);
    });

    if (!bounds.isEmpty()) {
      mapRef.current.fitBounds(bounds, { padding: 40, maxZoom: 13 });
    }
  }, [data, selectedIndex, displayMode]);

  return (
    <main className="page-shell">
      <section className="hero">
        <div>
          <p className="eyebrow">Citi Bike Revival</p>
          <h1>Station Capacity Forecast</h1>
          <p className="hero-copy">
            Forecasted bike and dock availability for selected Citi Bike stations over the next
            seven days.
          </p>
        </div>

        <div className="mode-toggle" aria-label="Display mode">
          <button
            className={displayMode === "bikes" ? "active" : ""}
            onClick={() => setDisplayMode("bikes")}
            type="button"
          >
            Bikes
          </button>
          <button
            className={displayMode === "docks" ? "active" : ""}
            onClick={() => setDisplayMode("docks")}
            type="button"
          >
            Docks
          </button>
        </div>
      </section>

      <section className="controls-card">
        <div>
          <span className="label">Prediction time</span>
          <strong>{selectedTimestamp ? formatDateTime(selectedTimestamp) : "Loading..."}</strong>
        </div>
        <input
          aria-label="Select prediction time"
          disabled={timestamps.length === 0}
          max={Math.max(timestamps.length - 1, 0)}
          min={0}
          onChange={(event) => setSelectedIndex(Number(event.target.value))}
          step={1}
          type="range"
          value={selectedIndex}
        />
        {data ? <span className="timestamp">Updated {formatDateTime(data.generatedAt)}</span> : null}
      </section>

      {isLoading ? <div className="state-card">Loading predictions...</div> : null}
      {error ? <div className="state-card error">Could not load predictions: {error}</div> : null}

      {!isLoading && !error ? (
        <section className="dashboard-grid">
          <div className="map-card">
            {mapboxToken ? (
              <div ref={mapContainerRef} className="map" />
            ) : (
              <div className="map map-fallback">
                Add `NEXT_PUBLIC_MAPBOX_TOKEN` to render the interactive map.
              </div>
            )}
          </div>

          <div className="table-card">
            <div className="table-header">
              <div>
                <span className="label">Stations</span>
                <h2>{displayMode === "bikes" ? "Bike Availability" : "Dock Availability"}</h2>
              </div>
              <span>{tableRows.length} stations</span>
            </div>

            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Station</th>
                    <th>Forecast</th>
                    <th>Current</th>
                  </tr>
                </thead>
                <tbody>
                  {tableRows.map((station) => (
                    <tr key={station.shortname}>
                      <td>
                        <strong>{station.name}</strong>
                        <span>{station.shortname}</span>
                      </td>
                      <td>{formatPercent(station.displayAvailability)}</td>
                      <td>
                        {station.currentBikeAvailability === null
                          ? "N/A"
                          : formatPercent(
                              displayMode === "bikes"
                                ? station.currentBikeAvailability
                                : 1 - station.currentBikeAvailability,
                            )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      ) : null}
    </main>
  );
}
