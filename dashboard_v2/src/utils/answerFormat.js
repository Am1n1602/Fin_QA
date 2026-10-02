import { formatCrore, LAKH } from "./format.js";

// The synthesis LLM (finqa_v2/reasoning/synthesize.py) writes the answer as plain prose --
// blank-line paragraphs, "- "/"1. " lists, **bold** spans. parseBlocks turns that into a
// small block list which EvidenceClaims.jsx renders as plain JSX, so React does the
// escaping and no HTML string is ever built.

const BULLET_RE = /^\s*[-*•]\s+(.*)$/;
const NUMBERED_RE = /^\s*(\d+)[.)]\s+(.*)$/;

// The synthesis LLM writes rupee amounts two ways -- as plain comma-grouped digits
// ("2,670,210,000,000.00 Indian rupees") or, just as often, pre-scaled with a Western
// magnitude word ("INR 1,033.63 billion") -- rewrite either into the same crore/lakh
// notation the structured evidence values use (utils/format.js), so the number in the
// prose matches the number in "Key findings" below it. Only amounts explicitly marked as
// rupees (a leading INR/Rs/rupees/₹ or a trailing INR/rupees) are touched: a bare
// "$4.7 billion", "12,483,000,000 shares" or "1,200,000 employees" is not INR and is left
// as written.
const SCALE_MULTIPLIER = { million: 1e6, billion: 1e9, trillion: 1e12 };
const AMOUNT = String.raw`(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?:\s*(trillion|billion|million)\b)?`;
const LEADING_INR_RE = new RegExp(String.raw`(?:\b(?:Indian rupees?|rupees?|INR|Rs\.?)|₹)\s*` + AMOUNT, "gi");
const TRAILING_INR_RE = new RegExp(AMOUNT + String.raw`\s*(?:Indian rupees?|rupees?|INR)\b`, "gi");
const LEADING_CURRENCY_WORD_RE = /\b(?:Indian rupees?|rupees?|INR|Rs\.?)\s+(₹[\d,.]+\s*(?:Cr|L))/gi;
const TRAILING_CURRENCY_WORD_RE = /(₹[\d,.]+\s*(?:Cr|L))\s+(?:Indian rupees?|rupees?|INR)\b\.?/gi;

function toCrore(match, digits, word) {
  const num = Number(digits.replace(/,/g, "")) * (word ? SCALE_MULTIPLIER[word.toLowerCase()] : 1);
  // A sub-lakh amount with no magnitude word is already readable as written.
  if (!Number.isFinite(num) || (!word && num < LAKH)) return match;
  return formatCrore(num);
}

export function reformatCurrencyNumbers(line) {
  return line
    .replace(LEADING_INR_RE, toCrore)
    .replace(TRAILING_INR_RE, toCrore)
    .replace(LEADING_CURRENCY_WORD_RE, "$1")
    .replace(TRAILING_CURRENCY_WORD_RE, "$1");
}

// Splitting on a capturing group alternates plain / bold: odd indices are the **bold** spans.
function inlineParts(line) {
  return reformatCurrencyNumbers(line).split(/\*\*(.+?)\*\*/g);
}

// -> [{ parts }]                                  a paragraph
//  | [{ ordered, start, items: [parts, ...] }]    a list (start = the number the LLM wrote
//    first, so "1. A / blank / 2. B" renders 1., 2. rather than restarting at 1.)
export function parseBlocks(text) {
  const lines = String(text ?? "").split("\n");
  const blocks = [];
  let paragraphLines = [];
  let list = null;

  function flushParagraph() {
    if (paragraphLines.length > 0) {
      blocks.push({ parts: inlineParts(paragraphLines.join(" ")) });
      paragraphLines = [];
    }
  }
  function flushList() {
    if (list) {
      blocks.push(list);
      list = null;
    }
  }

  for (const raw of lines) {
    const line = raw.trim();
    if (line === "") {
      flushParagraph();
      flushList();
      continue;
    }
    const bullet = BULLET_RE.exec(line);
    const numbered = NUMBERED_RE.exec(line);
    if (bullet || numbered) {
      flushParagraph();
      const ordered = Boolean(numbered);
      if (!list || list.ordered !== ordered) {
        flushList();
        list = { ordered, start: ordered ? Number(numbered[1]) : undefined, items: [] };
      }
      list.items.push(inlineParts(bullet ? bullet[1] : numbered[2]));
    } else {
      flushList();
      paragraphLines.push(line);
    }
  }
  flushParagraph();
  flushList();
  return blocks;
}
