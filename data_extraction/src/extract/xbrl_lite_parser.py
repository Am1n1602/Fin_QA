import json
import re
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


def derive_output_name(filepath: str, company: str) -> str:
    """Consolidated/Standalone + quarter-end date, parsed from the source
    filename, so each quarter/filing-type gets its own unique output file."""
    stem = Path(filepath).stem
    filing_type = "consolidated" if "consolidated" in stem.lower() else \
                  "standalone" if "standalone" in stem.lower() else "unknown"
    date_match = re.match(r"^(\d{2}-[A-Za-z]{3}-\d{4})", stem)
    period_tag = date_match.group(1) if date_match else stem[:20]
    return f"{company}_{filing_type}_{period_tag}"


def parse_and_save(filepath: str, company: str, out_dir: str = "data/extracted") -> tuple[Path, int]:
    """Parse one XBRL file and save its raw facts to disk. Returns
    (output_path, fact_count) — used by both the CLI below and
    run_extraction.py's multi-quarter batch runner."""
    recs = parse_xbrl_file(filepath, company)
    name = derive_output_name(filepath, company)
    out_path = Path(out_dir) / f"{name}_facts_raw.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
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
