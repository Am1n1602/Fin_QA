import React from "react";
import { formatValue } from "../utils/format.js";

export default function StatTile({ label, value, unit, period, limitations }) {
  const missing = value === null || value === undefined;
  return (
    <div className={`stat-tile${missing ? " stat-tile-missing" : ""}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{formatValue(value, unit)}</span>
      {period && <span className="stat-period">{period}</span>}
      {missing && limitations?.length > 0 && (
        <span className="stat-limitation" title={limitations.join("; ")}>
          not available
        </span>
      )}
    </div>
  );
}
