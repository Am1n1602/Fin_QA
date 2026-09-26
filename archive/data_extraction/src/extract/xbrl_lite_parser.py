import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from lxml import etree # type: ignore

NS = {
    "xbrli": "http://www.xbrl.org/2003/instance",
}

# Some filers (confirmed: HDFCBANK, ICICIBANK) self-declare DateOfEndOfReportingPeriod
# but omit DateOfStartOfReportingPeriod entirely -- unlike non-bank filers (confirmed:
# TCS), which declare both under the same context. Real reported magnitudes (interest
# income growing steadily quarter to quarter, never doubling/quadrupling) confirm the
# primary context is always the DISCRETE 3-month quarter, regardless of what the
# ReportingQuarter label itself says -- "Yearly"/"Fourth quarter" both mean the Q4
# quarter ending at FY end, not a cumulative full year (the true annual aggregate lives
# in a separate context that has no self-declared period at all and is not recovered
# here -- see docs/roadmap-v2-restart.md's HDFCBANK investigation, Phase 2/unresolved).
_QUARTER_INDEX = {
    "First quarter": 0,
    "Half yearly": 1,
    "Third quarter": 2,
    "Fourth quarter": 3,
    "Yearly": 3,
}


def _add_months(d: date, months: int) -> date:
    total = d.month - 1 + months
    return date(d.year + total // 12, total % 12 + 1, d.day)


def _derive_quarter_period(fy_start: str | None, reporting_quarter: str | None,
                            declared_end: str | None) -> tuple[str, str] | None:
    """Derive (start, end) for a context missing DateOfStartOfReportingPeriod, from
    DateOfStartOfFinancialYear + ReportingQuarter, cross-checked against the
    self-declared end date. Returns None (fail safe, no override applied) whenever the
    check doesn't hold -- an unexpected filing shape then keeps today's behavior
    (period_start stays unset) rather than risk mistagging a value."""
    n = _QUARTER_INDEX.get(reporting_quarter or "")
    if n is None or not fy_start or not declared_end:
        return None
    try:
        fy = date.fromisoformat(fy_start)
        end = date.fromisoformat(declared_end)
    except ValueError:
        return None
    start = _add_months(fy, 3 * n)
    if _add_months(start, 3) - timedelta(days=1) != end:
        return None
    return start.isoformat(), end.isoformat()


def _local_name(tag: str) -> str:
    """Strip the Clark-notation namespace off an lxml tag, e.g.
    '{http://www.xbrl.org/2003/instance}context' -> 'context'."""
    return tag.split("}")[-1] if "}" in tag else tag


def _qname(elem, nsmap_by_uri: dict) -> str:
    """Turn an lxml element's tag into 'prefix:localName' using the
    document's own namespace declarations (so tags read exactly like
    'in-capmkt:RevenueFromOperations', matching what you'd see in Arelle)."""
    if "}" not in elem.tag:
        return elem.tag
    uri, local = elem.tag[1:].split("}")
    prefix = nsmap_by_uri.get(uri, uri)
    return f"{prefix}:{local}"


def parse_xbrl_file(filepath: str, company: str = "") -> list[dict]:
    """Parse a local XBRL instance file. `filepath` is a normal local path
    — no URL resolution, no network access needed."""
    tree = etree.parse(filepath)
    root = tree.getroot()

    # Build a URI->prefix map from whatever this document declared, so
    # output tag names match the taxonomy's own prefixes (in-capmkt, etc.)
    nsmap_by_uri = {uri: prefix for prefix, uri in root.nsmap.items() if prefix}

    # --- Parse all contexts: id -> period info ---
    contexts = {}
    for ctx in root.iter(f"{{{NS['xbrli']}}}context"):
        ctx_id = ctx.get("id")
        period_el = ctx.find(f"{{{NS['xbrli']}}}period")
        instant = period_el.findtext(f"{{{NS['xbrli']}}}instant") if period_el is not None else None
        start = period_el.findtext(f"{{{NS['xbrli']}}}startDate") if period_el is not None else None
        end = period_el.findtext(f"{{{NS['xbrli']}}}endDate") if period_el is not None else None
        contexts[ctx_id] = {"instant": instant, "start": start, "end": end}

    # --- Parse all units: id -> measure text (e.g. "iso4217:INR") ---
    units = {}
    for unit in root.iter(f"{{{NS['xbrli']}}}unit"):
        unit_id = unit.get("id")
        measure = unit.findtext(f".//{{{NS['xbrli']}}}measure")
        units[unit_id] = measure

    # --- Self-declared reporting-period dates, keyed by context_id ---
    # Some filings (confirmed 2026-09-19 on real TCS "Financial Results" /
    # in-bse-fin taxonomy filings, pre-dating the Integrated Filing framework)
    # either omit a <context><period> definition for the primary duration
    # contexts entirely, or declare one that is flatly wrong: one real filing's
    # <context id="FourD"> declared a 3-month window while every value tagged
    # under it was a 12-month cumulative figure (confirmed against the
    # company's actual published full-year revenue). The same filings
    # separately self-describe each context's true period via plain facts --
    # DateOfStartOfReportingPeriod / DateOfEndOfReportingPeriod tagged under
    # the SAME context_id -- which were verified to match the real reported
    # values where the <context> definition did not. Prefer these over the
    # <context> XML's own period whenever both dates are present; otherwise
    # fall back to <context> unchanged (a no-op for filings without this
    # quirk, e.g. every Integrated Filing / in-capmkt document seen so far).
    self_described: dict[str, dict] = {}
    for elem in root.iter():
        ctx_ref = elem.get("contextRef")
        if ctx_ref is None:
            continue
        local = _local_name(elem.tag)
        if local == "DateOfStartOfReportingPeriod":
            self_described.setdefault(ctx_ref, {})["start"] = elem.text
        elif local == "DateOfEndOfReportingPeriod":
            self_described.setdefault(ctx_ref, {})["end"] = elem.text
        elif local == "ReportingQuarter":
            self_described.setdefault(ctx_ref, {})["quarter"] = elem.text
        elif local == "DateOfStartOfFinancialYear":
            self_described.setdefault(ctx_ref, {})["fy_start"] = elem.text

    for ctx_ref, info in self_described.items():
        if info.get("start") or not info.get("end"):
            continue  # either already resolvable, or nothing to derive from
        derived = _derive_quarter_period(info.get("fy_start"), info.get("quarter"), info["end"])
        if derived:
            info["start"], info["end"] = derived

    # --- Parse facts: any element with a contextRef is a fact ---
    records = []
    for elem in root.iter():
        ctx_ref = elem.get("contextRef")
        if ctx_ref is None:
            continue  # not a fact (context/unit/schemaRef/etc.)

        ctx = dict(contexts.get(ctx_ref, {}))
        override = self_described.get(ctx_ref)
        if override and override.get("start") and override.get("end"):
            ctx["start"], ctx["end"], ctx["instant"] = override["start"], override["end"], None
        unit_ref = elem.get("unitRef")

        records.append({
            "company": company,
            "line_item_tag": _qname(elem, nsmap_by_uri),
            "value": elem.text,
            "unit": units.get(unit_ref) if unit_ref else None,
            "context_id": ctx_ref,
            "period_start": ctx.get("start"),
            "period_end": ctx.get("end"),
            "instant": ctx.get("instant"),
            "decimals": elem.get("decimals"),
            "sign": elem.get("sign"),  # '-' if present, meaning value should be negated
            "source_doc": filepath,
        })

    return records


def derive_output_name(filepath: str, company: str) -> str:
    """Consolidated/Standalone + quarter-end date, parsed from the source
    filename, so each quarter/filing-type gets its own unique output file."""
    stem = Path(filepath).stem
    filing_type = "consolidated" if "consolidated" in stem.lower() else \
                  "standalone" if "standalone" in stem.lower() else "unknown"
    date_match = re.match(r"^(\d{2}-[A-Za-z]{3}-\d{4})", stem)
    period_tag = date_match.group(1) if date_match else stem[:20]
    return f"{company}_{filing_type}_{period_tag}"


def parse_and_save(filepath: str, company: str, out_dir: str | None = None) -> tuple[Path, int]:
    """Parse one XBRL file and save its raw facts to disk. Returns
    (output_path, fact_count) — used by both the CLI below and
    run_extraction.py's multi-quarter batch runner.

    `out_dir=None` resolves to src.config.EXTRACTED_DIR (the repo-root
    data_extraction/data/extracted/ finqa_v2 actually reads from) -- the old
    hardcoded relative default "data/extracted" silently wrote to
    <cwd>/data/extracted instead once this module's package moved into
    archive/, without ever raising an error (a stray archive/data_extraction/
    data/extracted/ directory accumulated real output that finqa_v2 never saw)."""
    if out_dir is None:
        from src.config import EXTRACTED_DIR

        out_dir = EXTRACTED_DIR
    recs = parse_xbrl_file(filepath, company)
    name = derive_output_name(filepath, company)
    out_path = Path(out_dir) / f"{name}_facts_raw.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        print(f"  [xbrl_lite_parser] NOTE: overwriting existing {out_path.name} "
              f"— this filing is replacing a previously processed one for the "
              f"same period (expected for Original -> Revision refilings).")
    out_path.write_text(json.dumps(recs, indent=2, default=str))
    return out_path, len(recs)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.extract.xbrl_lite_parser <local-path-to-.xbrl-file> [company_symbol]")
        sys.exit(1)
    path = sys.argv[1]
    company = sys.argv[2] if len(sys.argv) > 2 else ""

    out_path, n_facts = parse_and_save(path, company)
    print(f"Extracted {n_facts} facts (no network, no taxonomy needed).")
    print(f"Full fact list saved to {out_path}")

    recs = json.loads(out_path.read_text())
    KEYWORDS = [
        "revenue", "income", "expense", "profit", "tax", "eps",
        "asset", "liabilit", "equity", "reserve", "borrowing",
        "depreciation", "cash", "dividend",
    ]
    print(f"\n--- Facts matching financial-statement keywords ---")
    for r in recs:
        tag = (r["line_item_tag"] or "").lower()
        if any(kw in tag for kw in KEYWORDS):
            print(f"{r['line_item_tag']:70s} = {r['value']!s:20s} "
                  f"[ctx={r['context_id']}, period_end={r['period_end']}]")
