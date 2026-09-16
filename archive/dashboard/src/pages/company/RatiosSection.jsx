import React from "react";
import { api } from "../../api/client.js";
import { useApi } from "../../api/useApi.js";
import StatusBanner from "../../components/StatusBanner.jsx";
import { RATIO_METRICS, formatValue } from "../../constants/metrics.js";

export default function RatiosSection({ symbol, filingType }) {
  const { data, error, loading } = useApi(
    () => api.getRatios(symbol, { filingType }),
    [symbol, filingType]
  );

  return (
    <div className="card">
      <h2>Ratios</h2>
      <p className="byline" style={{ marginTop: 0 }}>
        Full computed ratio set -- latest available period per metric.
      </p>
      <StatusBanner loading={loading} error={error} loadingText={`Retrieving ${symbol} ratios...`}>
        {data && (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Metric</th>
                  <th scope="col" className="num">Value</th>
                  <th scope="col" className="num">Period</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.ratios).map(([metric, point]) => {
                  const meta = RATIO_METRICS[metric];
                  const formatted = point ? formatValue(point.value, meta?.unit) : null;
                  return (
                    <tr key={metric}>
                      <td>{meta?.label || metric}</td>
                      <td className="num">
                        {formatted !== null ? formatted : <span className="muted">no data</span>}
                      </td>
                      <td className="num">{point ? point.period : <span className="muted">&mdash;</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </StatusBanner>
    </div>
  );
}