import React from "react";

function fmt(value, unit) {
  if (value === null || value === undefined) return "—";
  const num = typeof value === "number" ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : value;
  return unit ? `${num} ${unit}` : `${num}`;
}

export default function StatTile({ label, value, unit, period, limitations }) {
  const missing = value === null || value === undefined;
  return (
    <div className={`stat-tile${missing ? " stat-tile-missing" : ""}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{fmt(value, unit)}</span>
      {period && <span className="stat-period">{period}</span>}
      {missing && limitations?.length > 0 && (
        <span className="stat-limitation" title={limitations.join("; ")}>
          not available
        </span>
      )}
    </div>
  );
}
