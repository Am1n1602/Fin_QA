const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export class ApiError extends Error {
  constructor(status, error, detail) {
    super(detail || error || `Request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.error = error;
    this.detail = detail;
  }
}

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  let body = null;
  try {
    body = await res.json();
  } catch {
    // A non-JSON body (e.g. a proxy/network-level error page) --
    // ApiError below falls back to statusText.
  }

  if (!res.ok) {
    throw new ApiError(res.status, body?.error, body?.detail || res.statusText);
  }
  return body;
}

function qs(params = {}) {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "");
  if (entries.length === 0) return "";
  return "?" + new URLSearchParams(entries).toString();
}

export const api = {
  health: () => request("/health"),

  listCompanies: () => request("/companies"),
  getCompany: (symbol, { filingType } = {}) =>
    request(`/companies/${symbol}${qs({ filing_type: filingType })}`),

  getFinancials: (symbol, { field, history, filingType } = {}) =>
    request(`/companies/${symbol}/financials${qs({ field, history, filing_type: filingType })}`),

  getRatios: (symbol, { metric, history, singleQuarterOnly, filingType } = {}) =>
    request(
      `/companies/${symbol}/ratios${qs({
        metric,
        history,
        single_quarter_only: singleQuarterOnly,
        filing_type: filingType,
      })}`
    ),

  getTrends: (symbol, { filingType } = {}) =>
    request(`/companies/${symbol}/trends${qs({ filing_type: filingType })}`),

  getPeers: (symbol, { filingType } = {}) =>
    request(`/companies/${symbol}/peers${qs({ filing_type: filingType })}`),

  getCompanyRanking: (symbol, { filingType } = {}) =>
    request(`/companies/${symbol}/ranking${qs({ filing_type: filingType })}`),

  getRankings: ({ sector, filingType } = {}) =>
    request(`/rankings${qs({ sector, filing_type: filingType })}`),

  getHealth: (symbol, { filingType } = {}) =>
    request(`/companies/${symbol}/health${qs({ filing_type: filingType })}`),

  getReport: (symbol, { filingType } = {}) =>
    request(`/companies/${symbol}/report${qs({ filing_type: filingType })}`),

  listSectors: () => request("/sectors"),
  getSectorComparison: (sector, { filingType } = {}) =>
    request(`/sectors/${encodeURIComponent(sector)}/comparison${qs({ filing_type: filingType })}`),

  askQuestion: (question) =>
    request("/qa", { method: "POST", body: JSON.stringify({ question }) }),
  askCompanyQuestion: (symbol, question) =>
    request(`/companies/${symbol}/qa`, { method: "POST", body: JSON.stringify({ question }) }),
};

export { BASE_URL };