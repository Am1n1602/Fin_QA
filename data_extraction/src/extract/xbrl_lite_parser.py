"""
Lightweight replacement for xbrl_parser.py (Arelle-based). Parses the XBRL
instance XML directly with lxml — no taxonomy schema, no network calls, no
DTS discovery. This works because everything we actually need (tag name,
value, period, unit) is self-contained in the instance document itself;
contexts and units are defined right there in the same file. We only
needed the taxonomy schema for things we don't use (labels, calculation
validation, presentation order).

pip install lxml
"""
import json
import sys
from pathlib import Path

from lxml import etree

NS = {
    "xbrli": "http://www.xbrl.org/2003/instance",
}


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

    # --- Parse facts: any element with a contextRef is a fact ---
    records = []
    for elem in root.iter():
        ctx_ref = elem.get("contextRef")
        if ctx_ref is None:
            continue  # not a fact (context/unit/schemaRef/etc.)

        ctx = contexts.get(ctx_ref, {})
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


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.extract.xbrl_lite_parser <local-path-to-.xbrl-file> [company_symbol]")
        sys.exit(1)
    path = sys.argv[1]
    company = sys.argv[2] if len(sys.argv) > 2 else ""

    recs = parse_xbrl_file(path, company)
    print(f"Extracted {len(recs)} facts (no network, no taxonomy needed).")


    stem = Path(path).stem
    if "consolidated" in stem.lower():
        filing_type = "consolidated"
    elif "standalone" in stem.lower():
        filing_type = "standalone"
    else:
        filing_type = stem[:40]  

    out_path = Path("data/extracted") / f"{company}_{filing_type}_facts_raw.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(recs, indent=2, default=str))
    print(f"Full fact list saved to {out_path}")

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
