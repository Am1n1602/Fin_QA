// Indian numbering (lakh/crore grouping) + unit-aware value formatting, shared by every
// table/tile that renders a Financial Engine value (finqa_v2 stores INR amounts in plain
// rupees -- see normalize/units.py -- so "INR" is rescaled to crore/lakh here, at the
// display edge only; nothing upstream changes).

export function formatIndianNumber(num, maxFractionDigits = 2) {
  if (typeof num !== "number" || !Number.isFinite(num)) return String(num);
  return num.toLocaleString("en-IN", { maximumFractionDigits: maxFractionDigits });
}

export const CRORE = 1e7;
export const LAKH = 1e5;

// Compact INR amount: crore above 1 Cr, lakh above 1 L, plain Indian-grouped rupees below
// that -- the scaled figure itself still gets Indian digit grouping (e.g. "2,10,972.80 Cr",
// not "210972.80 Cr"), since a bare 6-digit crore figure is exactly the unreadable number
// this whole format exists to avoid.
export function formatCrore(value, { decimals = 2, symbol = "₹" } = {}) {
  if (typeof value !== "number" || !Number.isFinite(value)) return String(value);
  const abs = Math.abs(value);
  if (abs >= CRORE) return `${symbol}${formatIndianNumber(value / CRORE, decimals)} Cr`;
  if (abs >= LAKH) return `${symbol}${formatIndianNumber(value / LAKH, decimals)} L`;
  return `${symbol}${formatIndianNumber(value, decimals)}`;
}

const UNIT_SUFFIX = { pct: "%", pp: " pp", x: "x" };

// Renders a (value, unit) pair the way the Financial Engine's EngineResult.unit vocabulary
// ('INR' | 'pct' | 'x' | 'ratio' | 'per_share' | 'shares' | 'pp', see finqa_v2/models.py)
// should read on screen -- crore-scaled currency, Indian digit grouping everywhere else.
export function formatValue(value, unit) {
  if (value === null || value === undefined) return "—";
  if (typeof value !== "number") return unit ? `${value} ${unit}` : String(value);

  if (unit === "INR") return formatCrore(value);
  if (unit === "per_share") return formatCrore(value, { decimals: 2 });
  if (unit === "shares") return formatIndianNumber(value, 0);
  if (unit in UNIT_SUFFIX) return `${formatIndianNumber(value)}${UNIT_SUFFIX[unit]}`;
  return unit ? `${formatIndianNumber(value)} ${unit}` : formatIndianNumber(value);
}
