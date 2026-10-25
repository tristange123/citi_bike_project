"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { FitBoundsOptions, LayerGroup, Map as LeafletMap } from "leaflet";

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
  geometry: LatLng[];
  estimated: boolean;
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

// Pins can only be dropped inside this Lower Manhattan box (the Battery up to about 20th St, river to river).
const lesSouthWest: LatLng = [40.7, -74.02];
const lesNorthEast: LatLng = [40.741, -73.97];

const legColors ={ walk: "#64748b", bike: "#1e64c8" };
const retryDelaysMs = [3000, 6000, 12000, 20000, 30000];
const maxDepartAheadMs = 7 * 24 * 60 * 60 * 1000 - 10 * 60 * 1000;

const nyInputFormat = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/New_York",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

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

// datetime-local value ("YYYY-MM-DDTHH:mm") for a moment in New York time.
function toNyInputValue(date: Date) {
  const parts = Object.fromEntries(nyInputFormat.formatToParts(date).map((part) => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

// Keep fitted content clear of the floating panel: left of it on desktop, above it on mobile.
function panelPadding(): FitBoundsOptions {
  const isWide = window.innerWidth > 640;
  return {
    paddingTopLeft: [isWide ? 420 : 24, 24],
    paddingBottomRight: [24, isWide ? 24 : Math.round(window.innerHeight * 0.55)],
  };
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

  const [view, setView] = useState<View>("navigate");
  const [pins, setPins] = useState<Pins>({ origin: null, destination: null });
  // Empty means "leave now"; otherwise a New York datetime-local value.
  const [departAt, setDepartAt] = useState("");
  const [nowValue, setNowValue] = useState("");
  const [routeData, setRouteData] = useState<RouteResponse | null>(null);
  const [routeError, setRouteError] = useState<string | null>(null);
  const [isRouteLoading, setIsRouteLoading] = useState(false);
  const [selectedRoute, setSelectedRoute] = useState(0);

  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<LeafletMap | null>(null);
  const markerLayerRef = useRef<LayerGroup | null>(null);
  const routeLayerRef = useRef<LayerGroup | null>(null);
  const routeAbortRef = useRef<AbortController | null>(null);
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
            setIsWakingServer(false);
          }
          return;
        } catch (err) {
          if (isCancelled) {
            return;
          }
          if (attempt === retryDelaysMs.length) {
            setError(err instanceof Error ? err.message : "Failed to load predictions");
            setIsLoading(false);
            setIsWakingServer(false);
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

  // "Now" is computed on the client only, and refreshed so the picker's minimum stays current.
  useEffect(() => {
    const update = () => setNowValue(toNyInputValue(new Date()));
    update();
    const interval = setInterval(update, 60 * 1000);
    return () => clearInterval(interval);
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
    if (!mapContainerRef.current || mapRef.current) {
      return;
    }

    let isMounted = true;

    async function initializeMap() {
      const L = await import("leaflet");
      if (!isMounted || !mapContainerRef.current || mapRef.current) {
        return;
      }

      const lesBounds = L.latLngBounds(lesSouthWest, lesNorthEast);
      const map = L.map(mapContainerRef.current, {
        maxBounds: lesBounds.pad(0.15),
        maxBoundsViscosity: 1,
        minZoom: 14,
        scrollWheelZoom: true,
        zoomControl: false,
      });
      map.fitBounds(lesBounds, panelPadding());
      L.control.zoom({ position: "bottomright" }).addTo(map);

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

      L.rectangle(lesBounds, {
        color: "#152033",
        dashArray: "6 6",
        fill: false,
        interactive: false,
        opacity: 0.5,
        weight: 1.5,
      }).addTo(map);

      // First click drops the start pin, second the destination; a third starts over.
      map.on("click", (event) => {
        if (viewRef.current !== "navigate" || !lesBounds.contains(event.latlng)) {
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
  }, []);

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

      const color = displayMode === "bikes" ? "#c81e00" : "#1e64c8";

      predictionData.stations.forEach((station) => {
        const availability = getAvailability(station, selectedIndex, displayMode);
        const radius = availability * 22 + 7;

        L.circleMarker([station.lat, station.lon], {
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
      });
    }

    renderMarkers();
  }, [data, isMapReady, selectedIndex, displayMode, view]);

  // Routes are only valid for the pins and time they were planned with.
  useEffect(() => {
    routeAbortRef.current?.abort();
    setRouteData(null);
    setRouteError(null);
    setIsRouteLoading(false);
  }, [pins, departAt]);

  async function generateRoutes() {
    if (!pins.origin || !pins.destination) {
      return;
    }

    routeAbortRef.current?.abort();
    const controller = new AbortController();
    routeAbortRef.current = controller;

    const params = new URLSearchParams({ from: formatPoint(pins.origin), to: formatPoint(pins.destination) });
    // A time that has already passed means leave now; the backend reads offset-less times as New York time.
    if (departAt && departAt > toNyInputValue(new Date())) {
      params.set("depart", `${departAt}:00`);
    }

    try {
      setIsRouteLoading(true);
      setRouteError(null);
      const response = await fetch(`${apiBaseUrl}/api/route?${params}`, { signal: controller.signal });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(body?.detail ?? `Route API returned ${response.status}`);
      }
      setRouteData(body);
      setSelectedRoute(body.recommendedIndex);
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
          const line = L.polyline(leg.geometry, {
            color: legColors[leg.mode],
            dashArray: leg.mode === "walk" ? "6 8" : undefined,
            opacity: isSelected ? 0.95 : 0.25,
            weight: isSelected ? (leg.mode === "bike" ? 6 : 4) : 3,
          }).addTo(layer);
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
        mapRef.current.fitBounds(bounds, { maxZoom: 16, ...panelPadding() });
      }
    }

    renderRoute();
  }, [isMapReady, view, pins, routeData, selectedRoute]);

  const navigateHint = !pins.origin
    ? "Click the map to drop your start pin."
    : !pins.destination
      ? "Click the map again to drop your destination."
      : routeData
        ? "Click the map to start a new trip."
        : "Pick a departure time, then generate routes.";

  const maxDepartValue = nowValue ? toNyInputValue(new Date(Date.now() + maxDepartAheadMs)) : "";

  return (
    <main className={`app-shell${view === "navigate" ? " navigating" : ""}`}>
      <div ref={mapContainerRef} className="map-fullscreen" />

      <aside className="panel">
        <header className="panel-header">
          <div>
            <p className="eyebrow">Citi Bike Revival</p>
            <h1>{view === "forecast" ? "Station Forecast" : "Navigator"}</h1>
          </div>
          <div className="mode-toggle" aria-label="View">
            <button
              className={view === "navigate" ? "active" : ""}
              onClick={() => setView("navigate")}
              type="button"
            >
              Navigate
            </button>
            <button
              className={view === "forecast" ? "active" : ""}
              onClick={() => setView("forecast")}
              type="button"
            >
              Forecast
            </button>
          </div>
        </header>

        {view === "navigate" ? (
          <>
            <section className="panel-section">
              <ol className="trip-pins">
                <li className={pins.origin ? "set" : ""}>
                  <span className="pin-dot start" />
                  <span>{pins.origin ? "Start pinned" : "Start: click the map"}</span>
                </li>
                <li className={pins.destination ? "set" : ""}>
                  <span className="pin-dot destination" />
                  <span>
                    {pins.destination ? "Destination pinned" : pins.origin ? "Destination: click the map" : "Destination"}
                  </span>
                </li>
              </ol>
              <button
                className="text-button"
                disabled={!pins.origin}
                onClick={() => setPins({ origin: null, destination: null })}
                type="button"
              >
                Clear pins
              </button>
            </section>

            <section className="panel-section">
              <label className="label" htmlFor="depart-at">
                Leave at
              </label>
              <div className="time-row">
                <input
                  id="depart-at"
                  max={maxDepartValue}
                  min={nowValue}
                  onChange={(event) => setDepartAt(event.target.value)}
                  type="datetime-local"
                  value={departAt || nowValue}
                />
                <button
                  className={`chip${departAt ? "" : " active"}`}
                  onClick={() => setDepartAt("")}
                  type="button"
                >
                  Now
                </button>
              </div>
            </section>

            <button
              className="generate-button"
              disabled={!pins.origin || !pins.destination || isRouteLoading}
              onClick={generateRoutes}
              type="button"
            >
              {isRouteLoading ? "Planning routes..." : "Generate routes"}
            </button>

            <p className="route-message">{navigateHint}</p>
            {isWakingServer ? (
              <p className="route-message">Waking up the server, the first request can take up to a minute...</p>
            ) : null}
            {routeError ? <p className="route-message error">{routeError}</p> : null}

            {routeData ? (
              <div className="route-list">
                {routeData.routes.map((route, index) => (
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
                {routeData.routes[selectedRoute]?.legs.some((leg) => leg.estimated) ? (
                  <p className="route-message">
                    Times are straight-line estimates and run optimistic across rivers and parks.
                  </p>
                ) : null}
              </div>
            ) : null}
          </>
        ) : (
          <>
            <section className="panel-section">
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

            <section className="panel-section">
              <span className="label">Prediction time</span>
              <strong>{selectedTimestamp ? formatDateTime(selectedTimestamp) : "Loading..."}</strong>
              <input
                aria-label="Select prediction time"
                className="slider"
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

            {isLoading ? (
              <p className="route-message">
                {isWakingServer
                  ? "Waking up the prediction server, this can take up to a minute..."
                  : "Loading predictions..."}
              </p>
            ) : null}
            {error ? <p className="route-message error">Could not load predictions: {error}</p> : null}

            {data ? (
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
            ) : null}
          </>
        )}
      </aside>
    </main>
  );
}
