const BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8010";

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
    // non-JSON body (network/proxy-level error page) -- ApiError falls back to statusText
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

  listCompanies: ({ index = "NIFTY 50" } = {}) => request(`/api/v2/companies${qs({ index })}`),
  getCompany: (ticker) => request(`/api/v2/companies/${ticker}`),
  getPeers: (ticker, { limit } = {}) => request(`/api/v2/companies/${ticker}/peers${qs({ limit })}`),

  getFinancial: (ticker, { metric, basis, period } = {}) =>
    request(`/api/v2/companies/${ticker}/financials${qs({ metric, basis, period })}`),

  getRatio: (ticker, { ratio, basis, period } = {}) =>
    request(`/api/v2/companies/${ticker}/ratios${qs({ ratio, basis, period })}`),
  decompose: (ticker, { metric, basis, period } = {}) =>
    request(`/api/v2/companies/${ticker}/ratios/decompose${qs({ metric, basis, period })}`),

  getGrowth: (ticker, { metric, kind, basis } = {}) =>
    request(`/api/v2/companies/${ticker}/growth${qs({ metric, kind, basis })}`),
  getCagr: (ticker, { metric, basis, years } = {}) =>
    request(`/api/v2/companies/${ticker}/growth/cagr${qs({ metric, basis, years })}`),

  getSegments: (ticker, { basis, period } = {}) =>
    request(`/api/v2/companies/${ticker}/segments${qs({ basis, period })}`),
  getSegmentGrowth: (ticker, { basis, kind } = {}) =>
    request(`/api/v2/companies/${ticker}/segments/growth${qs({ basis, kind })}`),

  getRankings: ({ metric, tickers, basis, period } = {}) =>
    request(`/api/v2/rankings${qs({ metric, tickers: tickers?.join(","), basis, period })}`),

  search: ({ q, company, k, mode } = {}) =>
    request(`/api/v2/search${qs({ q, company, k, mode })}`),
  getDocumentSection: (ticker, section, { financialYear, limit } = {}) =>
    request(`/api/v2/companies/${ticker}/documents/${section}${qs({ financial_year: financialYear, limit })}`),

  getResearch: (ticker, { useLlm = true } = {}) =>
    request(`/api/v2/companies/${ticker}/research${qs({ use_llm: useLlm })}`),
  askQuestion: (question, { useLlm = true } = {}) =>
    request("/api/v2/qa", { method: "POST", body: JSON.stringify({ question, use_llm: useLlm }) }),
};

export { BASE_URL };
