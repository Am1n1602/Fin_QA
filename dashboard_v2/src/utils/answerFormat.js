import Handlebars from "handlebars";
import { formatCrore, LAKH } from "./format.js";

// The synthesis LLM (finqa_v2/reasoning/synthesize.py) writes the answer as plain prose --
// blank-line paragraphs, "- "/"1. " lists, **bold** spans -- but the dashboard rendered it
// as one <p style="white-space:pre-wrap"> blob. This turns it into real HTML blocks via a
// Handlebars template instead of hand-built JSX, so the block markup lives in one place.

const TEMPLATE_SOURCE = `
{{#each blocks}}
  {{#if this.items}}
    {{#if this.ordered}}
      <ol class="answer-list">{{#each this.items}}<li>{{{this}}}</li>{{/each}}</ol>
    {{else}}
      <ul class="answer-list">{{#each this.items}}<li>{{{this}}}</li>{{/each}}</ul>
    {{/if}}
  {{else}}
    <p class="answer-paragraph">{{{this.text}}}</p>
  {{/if}}
{{/each}}
`;

const render = Handlebars.compile(TEMPLATE_SOURCE);

const BULLET_RE = /^\s*[-*•]\s+(.*)$/;
const NUMBERED_RE = /^\s*\d+[.)]\s+(.*)$/;

// The synthesis LLM writes rupee amounts two ways -- as plain comma-grouped digits
// ("2,670,210,000,000.00 Indian rupees") or, just as often, pre-scaled with a Western
// magnitude word ("INR 1,033.63 billion") -- rewrite either into the same crore/lakh
// notation the structured evidence values use (utils/format.js), so the number in the
// prose matches the number in "Key findings" below it. Runs on the raw line, before
// HTML-escaping: every character formatCrore introduces (digits, ",", ".", the rupee
// sign, "Cr"/"L") is HTML-safe.
const SCALE_WORD_RE = /\b(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(trillion|billion|million)\b/gi;
const SCALE_MULTIPLIER = { million: 1e6, billion: 1e9, trillion: 1e12 };
const BIG_NUMBER_RE = /\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b/g;
const LEADING_CURRENCY_WORD_RE = /\b(?:Indian rupees?|rupees?|INR|Rs\.?)\s+(₹[\d,.]+\s*(?:Cr|L))/gi;
const TRAILING_CURRENCY_WORD_RE = /(₹[\d,.]+\s*(?:Cr|L))\s+(?:Indian rupees?|rupees?|INR)\b\.?/gi;

export function reformatCurrencyNumbers(line) {
  const withScaleWords = line.replace(SCALE_WORD_RE, (match, digits, word) => {
    const num = Number(digits.replace(/,/g, "")) * SCALE_MULTIPLIER[word.toLowerCase()];
    return Number.isFinite(num) ? formatCrore(num) : match;
  });
  const withScaled = withScaleWords.replace(BIG_NUMBER_RE, (match) => {
    const num = Number(match.replace(/,/g, ""));
    if (!Number.isFinite(num) || Math.abs(num) < LAKH) return match;
    return formatCrore(num);
  });
  return withScaled.replace(LEADING_CURRENCY_WORD_RE, "$1").replace(TRAILING_CURRENCY_WORD_RE, "$1");
}

// Escape first, then apply **bold** on the escaped text -- Handlebars.escapeExpression
// doesn't touch "*", so this order can't reopen an HTML injection via the markdown pass.
function inlineFormat(line) {
  const escaped = Handlebars.escapeExpression(reformatCurrencyNumbers(line));
  return escaped.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

function parseBlocks(text) {
  const lines = String(text ?? "").split("\n");
  const blocks = [];
  let paragraphLines = [];
  let list = null;

  function flushParagraph() {
    if (paragraphLines.length > 0) {
      blocks.push({ text: inlineFormat(paragraphLines.join(" ")) });
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
        list = { ordered, items: [] };
      }
      list.items.push(inlineFormat((bullet || numbered)[1]));
    } else {
      flushList();
      paragraphLines.push(line);
    }
  }
  flushParagraph();
  flushList();
  return blocks;
}

export function renderAnswerHtml(text) {
  return render({ blocks: parseBlocks(text) });
}
