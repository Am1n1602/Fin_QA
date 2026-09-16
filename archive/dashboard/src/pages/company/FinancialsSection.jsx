import React from "react";
import { api } from "../../api/client.js";
import { useApi } from "../../api/useApi.js";
import StatusBanner from "../../components/StatusBanner.jsx";
import { FACT_FIELDS } from "../../constants/metrics.js";

export default function FinancialsSection({ symbol, filingType }) {
  const { data, error, loading } = useApi(
    () => api.getFinancials(symbol, { filingType }),
    [symbol, filingType]
  );

  return (
    <div className="card">
      <h2>Financials (as reported)</h2>
      <p className="byline" style={{ marginTop: 0 }}>
        Raw extracted facts -- consolidated XBRL line items, latest available period per field.
      </p>
      <StatusBanner loading={loading} error={error} loadingText={`Retrieving ${symbol} financials...`}>
        {data && (
          <>
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Field</th>
                    <th scope="col" className="num">Value</th>
                    <th scope="col" className="num">Period</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(data.facts).map(([field, point]) => (
                    <tr key={field}>
                      <td>{FACT_FIELDS[field] || field}</td>
                      <td className="num">
                        {point ? point.value.toLocaleString("en-IN", { maximumFractionDigits: 2 }) : (
                          <span className="muted">no data</span>
                        )}
                      </td>
                      <td className="num">{point ? point.period : <span className="muted">&mdash;</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {data.warning && <p className="muted" style={{ marginTop: "0.9rem" }}>{data.warning}</p>}
          </>
        )}
      </StatusBanner>
    </div>
  );
}