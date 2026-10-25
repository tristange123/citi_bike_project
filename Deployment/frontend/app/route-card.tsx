type LatLng = [number, number];

export type RoutePoint = {
  name: string;
  lat: number;
  lon: number;
};

export type RouteStation = RoutePoint & {
  shortname: string;
  modeled: boolean;
  bikesNow: number;
  ebikesNow: number;
  docksNow: number;
  expectedAtArrival: number;
};

export type RouteLeg = {
  mode: "walk" | "bike";
  start: RoutePoint;
  end: RoutePoint;
  meters: number;
  seconds: number;
  geometry: LatLng[];
  estimated: boolean;
};

export type RouteOption = {
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

type Props = {
  route: RouteOption;
  isRecommended: boolean;
  isSelected: boolean;
  onSelect: () => void;
};

// Status colors always travel with a word, so the chance never reads by color alone.
const chanceLevels = [
  { min: 0.8, color: "#0ca30c", word: "Likely" },
  { min: 0.5, color: "#fab219", word: "Uncertain" },
  { min: 0, color: "#d03b3b", word: "Unlikely" },
];

const ringRadius = 20;
const ringCircumference = 2 * Math.PI * ringRadius;

function chanceLevel(value: number) {
  return chanceLevels.find((level) => value >= level.min) ?? chanceLevels[chanceLevels.length - 1];
}

function minutes(seconds: number) {
  return Math.max(1, Math.round(seconds / 60));
}

function clock(value: string) {
  return new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" }).format(new Date(value));
}

function ChanceRing({ value }: { value: number | null }) {
  const level = value === null ? null : chanceLevel(value);
  const filled = value === null ? 0 : Math.min(Math.max(value, 0), 1) * ringCircumference;
  return (
    <svg aria-hidden="true" className="chance-ring" height="52" viewBox="0 0 52 52" width="52">
      <circle className="chance-ring-track" cx="26" cy="26" fill="none" r={ringRadius} strokeWidth="5" />
      {level ? (
        <circle
          cx="26"
          cy="26"
          fill="none"
          r={ringRadius}
          stroke={level.color}
          strokeDasharray={`${filled} ${ringCircumference}`}
          strokeLinecap={filled > 0 ? "round" : "butt"}
          strokeWidth="5"
          transform="rotate(-90 26 26)"
        />
      ) : null}
      {value === null ? (
        <WalkIcon x={18} y={18} size={16} />
      ) : (
        <text className="chance-ring-label" dominantBaseline="central" textAnchor="middle" x="26" y="26">
          {/* The model's chance only approaches 1, so a rounded "100%" would overstate it. */}
          {Math.min(99, Math.round(value * 100))}%
        </text>
      )}
    </svg>
  );
}

function WalkIcon({ x = 0, y = 0, size = 14 }: { x?: number; y?: number; size?: number }) {
  return (
    <svg aria-hidden="true" height={size} viewBox="0 0 16 16" width={size} x={x} y={y}>
      <g fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5">
        <circle cx="9" cy="2.75" r="1.25" />
        <path d="M8.5 5.5 7 10l2.5 2 .75 3M7 10l-1.5 5M8.5 5.5 11 8l2 .5M8.5 5.5 6 7l-1 2.5" />
      </g>
    </svg>
  );
}

function BikeIcon({ size = 14 }: { size?: number }) {
  return (
    <svg aria-hidden="true" height={size} viewBox="0 0 16 16" width={size}>
      <g fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5">
        <circle cx="3.5" cy="11" r="2.75" />
        <circle cx="12.5" cy="11" r="2.75" />
        <path d="M3.5 11 6 6h5l1.5 5M6 6l2.5 5h4M5.5 4h2M10 4h1.5l-.5 2" />
      </g>
    </svg>
  );
}

export function RouteCard({ route, isRecommended, isSelected, onSelect }: Props) {
  const hasBike = route.pickup !== null;
  const level = hasBike ? chanceLevel(route.reliability) : null;
  const totalLegSeconds = route.legs.reduce((sum, leg) => sum + leg.seconds, 0) || 1;

  return (
    <button className={`route-card${isSelected ? " selected" : ""}`} onClick={onSelect} type="button">
      <div className="route-summary">
        <ChanceRing value={hasBike ? route.reliability : null} />

        <div className="route-heading">
          <div className="route-title-row">
            <span className="route-label">{route.label}</span>
            {isRecommended ? <span className="route-badge">Recommended</span> : null}
          </div>
          <span className="route-times">
            {clock(route.departAt)} – {clock(route.arriveAt)}
          </span>
          <span className="route-chance">
            {level ? (
              <>
                <span className="chance-dot" style={{ background: level.color }} />
                {level.word} · bike and dock
              </>
            ) : (
              "Walking only, no bike needed"
            )}
          </span>
        </div>

        <div className="route-duration">
          <strong>{minutes(route.totalSeconds)}</strong>
          <span>min</span>
        </div>
      </div>

      <div aria-hidden="true" className="route-bar">
        {route.legs.map((leg, index) => (
          <span className={leg.mode} key={index} style={{ flexGrow: leg.seconds / totalLegSeconds }} />
        ))}
      </div>

      <ol className="route-steps">
        {route.legs.map((leg, index) => (
          <li className={leg.mode} key={index}>
            <span className="step-icon">{leg.mode === "walk" ? <WalkIcon /> : <BikeIcon />}</span>
            <span className="step-text">
              {leg.mode === "walk" ? "Walk" : "Ride"} to {leg.end.name}
            </span>
            <span className="step-time">{minutes(leg.seconds)} min</span>
          </li>
        ))}
      </ol>

      {route.pickup && route.dropoff ? (
        <div className="route-stations">
          <div>
            <span className="label">Pickup</span>
            <strong>{route.pickup.bikesNow} bikes now</strong>
            <span>~{Math.floor(route.pickup.expectedAtArrival)} when you arrive</span>
          </div>
          <div>
            <span className="label">Drop-off</span>
            <strong>~{Math.floor(route.dropoff.expectedAtArrival)} open docks</strong>
            <span>{route.dropoff.modeled ? "forecast on arrival" : "estimated on arrival"}</span>
          </div>
        </div>
      ) : null}
    </button>
  );
}
