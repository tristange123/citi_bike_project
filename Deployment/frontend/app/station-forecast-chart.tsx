"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

export type ForecastPoint = {
  time: number;
  value: number;
};

type Props = {
  points: ForecastPoint[];
  max: number;
  color: string;
  formatValue: (value: number) => string;
  // Axis labels stay short; the chart's title names the unit.
  formatTick?: (value: number) => string;
  // Optional time to mark with a reference line, such as the forecast slider's hour.
  markerTime?: number | null;
};

const height = 240;
const margin = { top: 16, right: 16, bottom: 30, left: 40 };

const nyHour = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", hourCycle: "h23" });
const nyDay = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", weekday: "short", day: "numeric" });
const nyMoment = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  weekday: "short",
  month: "short",
  day: "numeric",
  hour: "numeric",
});

// Clean ticks from 0 to max, always ending on max itself (the station's dock count).
function valueTicks(max: number) {
  const step = [1, 2, 5, 10, 20, 25, 50, 100].find((candidate) => candidate >= max / 4) ?? 100;
  const ticks: number[] = [];
  for (let value = 0; value <= max - step / 2; value += step) {
    ticks.push(value);
  }
  ticks.push(max);
  return ticks;
}

export function StationForecastChart({
  points,
  max,
  color,
  formatValue,
  formatTick = String,
  markerTime = null,
}: Props) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [width, setWidth] = useState(640);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);

  // Draw at the rendered pixel width so text and strokes are never scaled.
  useEffect(() => {
    const wrapper = wrapperRef.current;
    if (!wrapper) {
      return;
    }
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280, Math.round(entry.contentRect.width))));
    observer.observe(wrapper);
    return () => observer.disconnect();
  }, []);

  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;
  const safeMax = Math.max(max, 1);
  const start = points[0]?.time ?? 0;
  const end = points[points.length - 1]?.time ?? start + 1;
  const span = Math.max(end - start, 1);

  const x = (time: number) => margin.left + ((time - start) / span) * innerWidth;
  const y = (value: number) => margin.top + innerHeight - (Math.min(Math.max(value, 0), safeMax) / safeMax) * innerHeight;

  const geometry = useMemo(() => {
    const coords = points.map((point) => [x(point.time), y(point.value)] as const);
    const line = coords.map(([px, py], index) => `${index === 0 ? "M" : "L"}${px.toFixed(1)},${py.toFixed(1)}`).join("");
    const baseline = y(0);
    const area = coords.length
      ? `${line}L${coords[coords.length - 1][0].toFixed(1)},${baseline}L${coords[0][0].toFixed(1)},${baseline}Z`
      : "";

    const hours = points.map((point) => Number(nyHour.format(point.time)));
    // Midnights get gridlines; noons carry the day label, centered on the day.
    const midnights = points.filter((_, index) => hours[index] === 0).map((point) => point.time);
    const noons = points.filter((_, index) => hours[index] === 12).map((point) => point.time);
    return { line, area, midnights, noons };
    // x and y are derived from width, start, span and max, which are listed instead.
  }, [points, width, safeMax, start, span]);

  const ticks = valueTicks(safeMax);
  const active = activeIndex === null ? null : points[activeIndex];

  function indexAt(clientX: number) {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect || points.length === 0) {
      return null;
    }
    const fraction = (clientX - rect.left - margin.left) / innerWidth;
    return Math.min(points.length - 1, Math.max(0, Math.round(fraction * (points.length - 1))));
  }

  function handlePointerMove(event: PointerEvent<SVGSVGElement>) {
    setActiveIndex(indexAt(event.clientX));
  }

  function handleKeyDown(event: KeyboardEvent<SVGSVGElement>) {
    const step = event.shiftKey ? 24 : 1;
    const current = activeIndex ?? 0;
    const next =
      event.key === "ArrowRight"
        ? current + step
        : event.key === "ArrowLeft"
          ? current - step
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? points.length - 1
              : null;
    if (next === null) {
      return;
    }
    event.preventDefault();
    setActiveIndex(Math.min(points.length - 1, Math.max(0, next)));
  }

  const activeX = active ? x(active.time) : 0;
  const activeY = active ? y(active.value) : 0;
  const tooltipAlign = activeX < width * 0.2 ? "start" : activeX > width * 0.8 ? "end" : "middle";
  const showMarker = markerTime !== null && markerTime >= start && markerTime <= end;

  return (
    <div className="forecast-chart" ref={wrapperRef}>
      <svg
        aria-label={`Hourly forecast over the next 7 days. Use the arrow keys to read values.`}
        height={height}
        onBlur={() => setActiveIndex(null)}
        onFocus={() => setActiveIndex((index) => index ?? 0)}
        onKeyDown={handleKeyDown}
        onPointerLeave={() => setActiveIndex(null)}
        onPointerMove={handlePointerMove}
        ref={svgRef}
        role="img"
        tabIndex={0}
        viewBox={`0 0 ${width} ${height}`}
        width={width}
      >
        {ticks.map((value) => (
          <g key={value}>
            <line className="chart-grid" x1={margin.left} x2={width - margin.right} y1={y(value)} y2={y(value)} />
            <text className="chart-axis" dominantBaseline="middle" textAnchor="end" x={margin.left - 8} y={y(value)}>
              {formatTick(value)}
            </text>
          </g>
        ))}

        {geometry.midnights.map((time) => (
          <line
            className="chart-grid"
            key={time}
            x1={x(time)}
            x2={x(time)}
            y1={margin.top}
            y2={margin.top + innerHeight}
          />
        ))}
        {geometry.noons.map((time) => (
          <text className="chart-axis" key={time} textAnchor="middle" x={x(time)} y={height - 10}>
            {nyDay.format(time)}
          </text>
        ))}

        {showMarker ? (
          <line
            className="chart-marker"
            x1={x(markerTime)}
            x2={x(markerTime)}
            y1={margin.top}
            y2={margin.top + innerHeight}
          />
        ) : null}

        <path d={geometry.area} fill={color} fillOpacity={0.1} />
        <path
          d={geometry.line}
          fill="none"
          stroke={color}
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
        />
        <line className="chart-baseline" x1={margin.left} x2={width - margin.right} y1={y(0)} y2={y(0)} />

        {active ? (
          <g pointerEvents="none">
            <line className="chart-crosshair" x1={activeX} x2={activeX} y1={margin.top} y2={margin.top + innerHeight} />
            <circle cx={activeX} cy={activeY} fill={color} r={4.5} stroke="var(--card)" strokeWidth={2} />
          </g>
        ) : null}
      </svg>

      {active ? (
        <div
          className={`chart-tooltip ${tooltipAlign}`}
          style={{ left: activeX, top: activeY }}
        >
          <strong>{formatValue(active.value)}</strong>
          <span>{nyMoment.format(active.time)}</span>
        </div>
      ) : null}
    </div>
  );
}
