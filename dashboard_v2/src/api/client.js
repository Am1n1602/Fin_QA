// `??` (not `||`) so an explicitly-empty string (the Docker build passes "" -- see
// dashboard.Dockerfile -- meaning "same origin, let nginx reverse-proxy /api/*") isn't
// overridden by the fallback; only a genuinely unset var (plain `npm run dev`) is.
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8010";

export class ApiError extends Error {
  constructor(status, error, detail) {
    super(detail || error || `Request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.error = error;
    this.detail = detail;
  }
}

async function fetchJson(path, options) {
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
    // FastAPI's own 422 validation errors send `detail` as a list of {loc, msg, type}
    // objects (only this API's ApiError subclasses send a string) -- flatten it so
    // anything that renders `error.detail` always gets text.
    const detail = Array.isArray(body?.detail) ? body.detail.map((e) => e.msg).join("; ") : body?.detail;
    throw new ApiError(res.status, body?.error, detail || res.statusText);
  }
  return body;
}

// Plain GET responses are static until the API restarts (see finqa_v2/api/cache.py), so
// repeat visits to a tab (Financials/Ratios/Trends each fan out 4-9 calls) reuse the
// first response. Skipped for /health (a live status), POSTs, and any call carrying an
// AbortSignal (those are the slow LLM-backed ones, which must stay individually cancellable).
const getCache = new Map();

function request(path, options = {}) {
  const cacheable = !options.method && !options.signal && path !== "/health";
  if (cacheable && getCache.has(path)) return getCache.get(path);
  const pending = fetchJson(path, options);
  if (cacheable) {
    getCache.set(path, pending);
    pending.catch(() => getCache.delete(path));
  }
  return pending;
}

function qs(params = {}) {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "");
  if (entries.length === 0) return "";
  return "?" + new URLSearchParams(entries).toString();
}

export const api = {
  health: ({ signal } = {}) => request("/health", { signal }),

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

  getResearch: (ticker, { useLlm = true, signal } = {}) =>
    request(`/api/v2/companies/${ticker}/research${qs({ use_llm: useLlm })}`, { signal }),
  askQuestion: (question, { useLlm = true } = {}) =>
    request("/api/v2/qa", { method: "POST", body: JSON.stringify({ question, use_llm: useLlm }) }),
};

export { BASE_URL };
