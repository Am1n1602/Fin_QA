export const RATIO_METRICS = {
  npm_pct: { label: "Net Profit Margin", unit: "pct" },
  pbt_margin_pct: { label: "PBT Margin", unit: "pct" },
  ebitda_margin_pct_approx: { label: "EBITDA Margin (approx.)", unit: "pct" },
  roe_pct: { label: "Return on Equity (ROE)", unit: "pct" },
  roa_pct: { label: "Return on Assets (ROA)", unit: "pct" },
  operating_roce_pct: { label: "Operating ROCE (Other Income excluded)", unit: "pct" },
  roce_pct: { label: "ROCE (incl. Other Income)", unit: "pct" },

  current_ratio: { label: "Current Ratio", unit: "x" },
  cash_ratio: { label: "Cash Ratio", unit: "x" },
  debt_to_equity: { label: "Debt / Equity", unit: "x" },
  interest_coverage_ratio: { label: "Interest Coverage", unit: "x" },
  asset_turnover: { label: "Asset Turnover", unit: "x" },
  net_debt_to_operating_ebit: { label: "Net Debt / Operating EBIT", unit: "x" },
  working_capital_to_assets_pct: { label: "Working Capital / Total Assets", unit: "pct" },
  equity_to_liabilities_pct: { label: "Equity / Total Liabilities", unit: "pct" },

  pe_ratio: { label: "P/E Ratio", unit: "x" },
  pb_ratio: { label: "P/B Ratio", unit: "x" },
  ev_to_sales: { label: "EV / Sales", unit: "x" },
  earnings_yield_pct: { label: "Earnings Yield", unit: "pct" },
  dividend_yield_pct: { label: "Dividend Yield", unit: "pct" },
  dividend_per_share: { label: "Dividend per Share", unit: "currency" },
  book_value_per_share: { label: "Book Value per Share", unit: "currency" },
  enterprise_value: { label: "Enterprise Value", unit: "currency" },
  ttm_eps: { label: "TTM EPS", unit: "currency" },
  latest_close: { label: "Latest Close Price", unit: "currency" },
};

export const FACT_FIELDS = {
  revenue: "Revenue",
  net_profit: "Net Profit",
  pbt: "Profit Before Tax",
  total_expenses: "Total Expenses",
  total_assets: "Total Assets",
  total_equity: "Total Equity",
  eps_basic: "EPS (Basic)",
  eps_diluted: "EPS (Diluted)",
  dividends: "Dividends (as reported)",
  operating_cash_flow: "Operating Cash Flow",
  finance_costs: "Finance Costs",
};

export const DEFAULT_COMPARISON_METRICS = [
  "npm_pct", "roe_pct", "operating_roce_pct", "roa_pct",
  "current_ratio", "debt_to_equity", "pe_ratio", "pb_ratio",
];

export const RANKING_CATEGORIES = [
  { key: "profitability", label: "Profitability" },
  { key: "capital_efficiency", label: "Capital Efficiency" },
  { key: "safety", label: "Safety" },
  { key: "valuation", label: "Valuation" },
];

export function metricLabel(key) {
  return RATIO_METRICS[key]?.label || FACT_FIELDS[key] || key;
}


export function formatValue(value, unit) {
  if (value === null || value === undefined) return null;
  if (typeof value !== "number" || Number.isNaN(value)) return String(value);
  if (unit === "pct") return `${value.toFixed(2)}%`;
  if (unit === "x") return `${value.toFixed(2)}x`;
  if (unit === "currency") return value.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  if (unit === "count") return value.toLocaleString("en-IN", { maximumFractionDigits: 0 });
  return value.toLocaleString("en-IN", { maximumFractionDigits: 4 });
}

export function formatGrowthPct(value) {
  if (value === null || value === undefined) return null;
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

export function formatChangeAbsolute(value) {
  if (value === null || value === undefined) return null;
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}