"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { LayerGroup, Map as LeafletMap } from "leaflet";

type DisplayMode = "bikes" | "docks";
type View = "forecast" | "navigate";
type LatLng = [number, number];

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

type RoutePoint = {
  name: string;
  lat: number;
  lon: number;
};

type RouteStation = RoutePoint & {
  shortname: string;
  modeled: boolean;
  bikesNow: number;
  ebikesNow: number;
  docksNow: number;
  expectedAtArrival: number;
};

type RouteLeg = {
  mode: "walk" | "bike";
  start: RoutePoint;
  end: RoutePoint;
  meters: number;
  seconds: number;
};

type RouteOption = {
  label: string;
  totalSeconds: number;
  expectedSeconds: number;
  reliability: number;
  departAt: string;
  arriveAt: string;
  legs: RouteLeg[];
  pickup: RouteStation | null;
  dropoff: RouteStation | null;
};

type RouteResponse = {
  generatedAt: string;
  routes: RouteOption[];
  recommendedIndex: number;
};

type Pins = {
  origin: LatLng | null;
  destination: LatLng | null;
};

const apiBaseUrl = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);

const cartoApiKey = process.env.NEXT_PUBLIC_CARTO_API_KEY ?? "";

const legColors ={ walk: "#64748b", bike: "#1e64c8" };
const retryDelaysMs = [3000, 6000, 12000, 20000, 30000];

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatClock(value: string) {
  return new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" }).format(new Date(value));
}

function formatMinutes(seconds: number) {
  return `${Math.max(1, Math.round(seconds / 60))} min`;
}

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function formatPoint([lat, lon]: LatLng) {
  return `${lat.toFixed(6)},${lon.toFixed(6)}`;
}

function getAvailability(station: StationPrediction, selectedIndex: number, mode: DisplayMode) {
  const prediction = station.predictions[selectedIndex];
  return mode === "bikes" ? prediction.bikeAvailability : prediction.dockAvailability;
}

export default function Home() {
  const [data, setData] = useState<PredictionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isWakingServer, setIsWakingServer] = useState(false);
  const [displayMode, setDisplayMode] = useState<DisplayMode>("bikes");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [isMapReady, setIsMapReady] = useState(false);

  const [view, setView] = useState<View>("forecast");
  const [pins, setPins] = useState<Pins>({ origin: null, destination: null });
  const [routeData, setRouteData] = useState<RouteResponse | null>(null);
  const [routeError, setRouteError] = useState<string | null>(null);
  const [isRouteLoading, setIsRouteLoading] = useState(false);
  const [selectedRoute, setSelectedRoute] = useState(0);

  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<LeafletMap | null>(null);
  const markerLayerRef = useRef<LayerGroup | null>(null);
  const routeLayerRef = useRef<LayerGroup | null>(null);
  // The map click handler is registered once, so it reads the current view through a ref.
  const viewRef = useRef<View>(view);
  viewRef.current = view;

  useEffect(() => {
    let isCancelled = false;

    async function loadPredictions() {
      setIsLoading(true);
      // A sleeping free-tier backend can take a minute or more to boot, so retry before failing.
      for (let attempt = 0; attempt <= retryDelaysMs.length; attempt += 1) {
        try {
          const response = await fetch(`${apiBaseUrl}/api/predictions`);
          if (!response.ok) {
            throw new Error(`Prediction API returned ${response.status}`);
          }
          const body = await response.json();
          if (!isCancelled) {
            setData(body);
            setError(null);
            setIsLoading(false);
          }
          return;
        } catch (err) {
          if (isCancelled) {
            return;
          }
          if (attempt === retryDelaysMs.length) {
            setError(err instanceof Error ? err.message : "Failed to load predictions");
            setIsLoading(false);
            return;
          }
          setIsWakingServer(true);
          await new Promise((resolve) => setTimeout(resolve, retryDelaysMs[attempt]));
        }
      }
    }

    loadPredictions();
    return () => {
      isCancelled = true;
    };
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
    if (isLoading || error || !mapContainerRef.current || mapRef.current) {
      return;
    }

    let isMounted = true;

    async function initializeMap() {
      const L = await import("leaflet");
      if (!isMounted || !mapContainerRef.current || mapRef.current) {
        return;
      }

      const map = L.map(mapContainerRef.current, {
        center: [40.73, -73.98],
        scrollWheelZoom: true,
        zoom: 12,
      });

      // CARTO serves an "API key required" placeholder without a key, so fall back to plain OSM tiles.
      if (cartoApiKey) {
        L.tileLayer(
          `https://basemaps.cartocdn.com/rastertiles/light_all/{z}/{x}/{y}{r}.png?key=${cartoApiKey}`,
          {
            attribution:
              '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
            maxZoom: 20,
          },
        ).addTo(map);
      } else {
        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
          attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
          maxZoom: 19,
        }).addTo(map);
      }

      // First click drops the start pin, second the destination; a third starts over.
      map.on("click", (event) => {
        if (viewRef.current !== "navigate") {
          return;
        }
        const point: LatLng = [event.latlng.lat, event.latlng.lng];
        setPins((previous) =>
          !previous.origin || previous.destination
            ? { origin: point, destination: null }
            : { origin: previous.origin, destination: point },
        );
      });

      markerLayerRef.current = L.layerGroup().addTo(map);
      routeLayerRef.current = L.layerGroup().addTo(map);
      mapRef.current = map;
      setIsMapReady(true);

      requestAnimationFrame(() => {
        map.invalidateSize();
      });
    }

    initializeMap();

    return () => {
      isMounted = false;
      setIsMapReady(false);
      mapRef.current?.remove();
      mapRef.current = null;
      markerLayerRef.current = null;
      routeLayerRef.current = null;
    };
  }, [error, isLoading]);

  useEffect(() => {
    if (!data || !isMapReady || !mapRef.current || !markerLayerRef.current) {
      return;
    }

    const predictionData = data;

    async function renderMarkers() {
      const L = await import("leaflet");
      if (!mapRef.current || !markerLayerRef.current) {
        return;
      }

      markerLayerRef.current.clearLayers();
      if (view === "navigate") {
        return;
      }

      const bounds = L.latLngBounds([]);
      const color = displayMode === "bikes" ? "#c81e00" : "#1e64c8";

      predictionData.stations.forEach((station) => {
        const availability = getAvailability(station, selectedIndex, displayMode);
        const latLng: [number, number] = [station.lat, station.lon];
        const radius = availability * 22 + 7;

        L.circleMarker(latLng, {
          className: "station-marker",
          color: "#ffffff",
          fillColor: color,
          fillOpacity: 0.72,
          opacity: 1,
          radius,
          weight: 2,
        })
          .bindPopup(
            `<strong>${station.name}</strong><br/>${displayMode === "bikes" ? "Bike" : "Dock"} availability: ${formatPercent(
              availability,
            )}`,
          )
          .addTo(markerLayerRef.current!);

        bounds.extend(latLng);
      });

      if (bounds.isValid()) {
        mapRef.current.fitBounds(bounds, { maxZoom: 13, padding: [40, 40] });
        requestAnimationFrame(() => {
          mapRef.current?.invalidateSize();
        });
      }
    }

    renderMarkers();
  }, [data, isMapReady, selectedIndex, displayMode, view]);

  useEffect(() => {
    if (!pins.origin || !pins.destination) {
      setRouteData(null);
      setRouteError(null);
      return;
    }

    const controller = new AbortController();
    const url = `${apiBaseUrl}/api/route?from=${formatPoint(pins.origin)}&to=${formatPoint(pins.destination)}`;

    async function loadRoute() {
      try {
        setIsRouteLoading(true);
        const response = await fetch(url, { signal: controller.signal });
        const body = await response.json().catch(() => null);
        if (!response.ok) {
          throw new Error(body?.detail ?? `Route API returned ${response.status}`);
        }
        setRouteData(body);
        setSelectedRoute(body.recommendedIndex);
        setRouteError(null);
      } catch (err) {
        if (controller.signal.aborted) {
          return;
        }
        setRouteData(null);
        setRouteError(err instanceof Error ? err.message : "Failed to plan route");
      } finally {
        if (!controller.signal.aborted) {
          setIsRouteLoading(false);
        }
      }
    }

    loadRoute();
    return () => controller.abort();
  }, [pins]);

  useEffect(() => {
    if (!isMapReady || !mapRef.current || !routeLayerRef.current) {
      return;
    }

    async function renderRoute() {
      const L = await import("leaflet");
      const layer = routeLayerRef.current;
      if (!mapRef.current || !layer) {
        return;
      }

      layer.clearLayers();
      if (view !== "navigate") {
        return;
      }

      const bounds = L.latLngBounds([]);
      const routes = routeData?.routes ?? [];

      // Unselected options stay faintly visible underneath the selected one.
      routes.forEach((route, index) => {
        const isSelected = index === selectedRoute;
        route.legs.forEach((leg) => {
          const line = L.polyline(
            [
              [leg.start.lat, leg.start.lon],
              [leg.end.lat, leg.end.lon],
            ],
            {
              color: legColors[leg.mode],
              dashArray: leg.mode === "walk" ? "6 8" : undefined,
              opacity: isSelected ? 0.95 : 0.25,
              weight: isSelected ? (leg.mode === "bike" ? 6 : 4) : 3,
            },
          ).addTo(layer);
          if (isSelected) {
            line.bringToFront();
            bounds.extend(line.getBounds());
          } else {
            line.on("click", () => setSelectedRoute(index));
          }
        });
      });

      const route = routes[selectedRoute];
      [route?.pickup, route?.dropoff].forEach((station, index) => {
        if (!station) {
          return;
        }
        const detail =
          index === 0
            ? `${station.bikesNow} bikes now (${station.ebikesNow} e-bikes), ~${station.expectedAtArrival} on arrival`
            : `${station.docksNow} docks now, ~${station.expectedAtArrival} on arrival`;
        L.circleMarker([station.lat, station.lon], {
          color: "#ffffff",
          fillColor: legColors.bike,
          fillOpacity: 1,
          radius: 8,
          weight: 2,
        })
          .bindPopup(`<strong>${station.name}</strong><br/>${detail}`)
          .addTo(layer);
      });

      const pinStyles: [LatLng | null, string, string][] = [
        [pins.origin, "#16a34a", "Start"],
        [pins.destination, "#152033", "Destination"],
      ];
      pinStyles.forEach(([point, color, label]) => {
        if (!point) {
          return;
        }
        L.circleMarker(point, { color: "#ffffff", fillColor: color, fillOpacity: 1, radius: 10, weight: 3 })
          .bindTooltip(label)
          .addTo(layer);
        bounds.extend(point);
      });

      if (routeData && bounds.isValid()) {
        mapRef.current.fitBounds(bounds, { maxZoom: 16, padding: [60, 60] });
      }
    }

    renderRoute();
  }, [isMapReady, view, pins, routeData, selectedRoute]);

  const navigateHint = !pins.origin
    ? "Click the map to drop your start pin."
    : !pins.destination
      ? "Click the map again to drop your destination."
      : isRouteLoading
        ? "Planning routes..."
        : "Click the map to start a new trip.";

  return (
    <main className="page-shell">
      <section className="hero">
        <div>
          <p className="eyebrow">Citi Bike Revival</p>
          <h1>{view === "forecast" ? "Station Capacity Forecast" : "Citi Bike Navigator"}</h1>
          <p className="hero-copy">
            {view === "forecast"
              ? "Forecasted bike and dock availability for selected Citi Bike stations over the next seven days."
              : "Drop two pins to compare walk + bike routes, ranked by travel time and the chance a bike and dock will be there."}
          </p>
        </div>

        <div className="hero-controls">
          <div className="mode-toggle" aria-label="View">
            <button
              className={view === "forecast" ? "active" : ""}
              onClick={() => setView("forecast")}
              type="button"
            >
              Forecast
            </button>
            <button
              className={view === "navigate" ? "active" : ""}
              onClick={() => setView("navigate")}
              type="button"
            >
              Navigate
            </button>
          </div>

          {view === "forecast" ? (
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
          ) : null}
        </div>
      </section>

      {view === "forecast" ? (
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
      ) : (
        <section className="controls-card navigate-controls">
          <div>
            <span className="label">Trip</span>
            <strong>{navigateHint}</strong>
          </div>
          <button
            className="reset-button"
            disabled={!pins.origin}
            onClick={() => setPins({ origin: null, destination: null })}
            type="button"
          >
            Clear pins
          </button>
        </section>
      )}

      {isLoading ? (
        <div className="state-card">
          {isWakingServer
            ? "Waking up the prediction server, this can take up to a minute..."
            : "Loading predictions..."}
        </div>
      ) : null}
      {error ? <div className="state-card error">Could not load predictions: {error}</div> : null}

      {!isLoading && !error ? (
        <section className="dashboard-grid">
          <div className={`map-card${view === "navigate" ? " navigating" : ""}`}>
            <div ref={mapContainerRef} className="map" />
          </div>

          {view === "forecast" ? (
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
          ) : (
            <div className="table-card">
              <div className="table-header">
                <div>
                  <span className="label">Routes</span>
                  <h2>Trip Options</h2>
                </div>
                {routeData ? <span>{routeData.routes.length} options</span> : null}
              </div>

              <div className="table-scroll route-list">
                {routeError ? <p className="route-message error">{routeError}</p> : null}
                {!routeData && !routeError ? <p className="route-message">{navigateHint}</p> : null}
                {routeData?.routes.map((route, index) => (
                  <button
                    className={`route-card${index === selectedRoute ? " selected" : ""}`}
                    key={`${route.label}-${index}`}
                    onClick={() => setSelectedRoute(index)}
                    type="button"
                  >
                    <div className="route-card-header">
                      <span className="route-label">
                        {route.label}
                        {index === routeData.recommendedIndex ? <em>recommended</em> : null}
                      </span>
                      <strong>{formatMinutes(route.totalSeconds)}</strong>
                    </div>
                    <span className="route-meta">
                      {formatClock(route.departAt)} → {formatClock(route.arriveAt)} ·{" "}
                      {route.pickup ? `${formatPercent(route.reliability)} chance bike + dock` : "no bike needed"}
                    </span>
                    <ol className="route-legs">
                      {route.legs.map((leg, legIndex) => (
                        <li className={leg.mode} key={legIndex}>
                          {leg.mode === "walk" ? "Walk" : "Ride"} {formatMinutes(leg.seconds)} to {leg.end.name}
                        </li>
                      ))}
                    </ol>
                    {route.pickup && route.dropoff ? (
                      <span className="route-meta">
                        {route.pickup.bikesNow} bikes at pickup now · ~{Math.floor(route.dropoff.expectedAtArrival)} docks
                        free at drop-off on arrival
                        {route.dropoff.modeled ? " (forecast)" : ""}
                      </span>
                    ) : null}
                  </button>
                ))}
                {routeData ? (
                  <p className="route-message">
                    Times are straight-line estimates and run optimistic across rivers and parks.
                  </p>
                ) : null}
              </div>
            </div>
          )}
        </section>
      ) : null}
    </main>
  );
}
