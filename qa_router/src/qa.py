from __future__ import annotations

from src import database_ro
from src import llm_integration
from src import metrics as metrics_mod
from src import query_expansion
from src.bridges.analysis_bridge import AnalysisBridge
from src.bridges.rag_bridge import RagBridge
from src.classify import (
    INTENT_COMPARISON,
    INTENT_COMPLEX,
    INTENT_FINANCIAL_HEALTH,
    INTENT_NARRATIVE,
    INTENT_NUMERIC_FACT,
    INTENT_RANKING,
    INTENT_REPORT,
    INTENT_TREND,
    INTENT_UNKNOWN,
    Classification,
    classify_question,
)
from src.config import DB_PATH


def _fmt_value(value, unit_hint: str | None) -> str:
    if value is None:
        return "N/A"
    if unit_hint == "pct":
        return f"{value:.2f}%"
    if unit_hint == "x":
        return f"{value:.2f}x"
    if unit_hint == "currency":
        return f"{value:,.2f}"
    return f"{value:,.4f}" if isinstance(value, float) else str(value)


def _default_universe(db_path: str) -> list[str]:
    return [c["symbol"] for c in database_ro.list_companies(db_path)]


def _handle_numeric_fact(q: Classification, db_path: str) -> dict:
    symbol = q.companies[0]
    lines: list[str] = []
    data: dict = {}
    sources: list[dict] = []
    facts_included = False

    for metric_key in q.metrics:
        m = metrics_mod.get(metric_key)
        if m.table == "financial_metrics":
            point = database_ro.latest_metric(db_path, symbol, q.filing_type, m.field)
        else:
            point = database_ro.latest_fact(db_path, symbol, q.filing_type, m.field)
            facts_included = True
        data[metric_key] = point
        if point is None:
            lines.append(f"{m.label} for {symbol} ({q.filing_type}): not available in the database.")
            continue
        lines.append(
            f"{symbol}'s {m.label} as of {point['period']} ({q.filing_type}) "
            f"was {_fmt_value(point['value'], m.unit_hint)}."
        )
        sources.append({
            "type": m.table, "company": symbol, "field": m.field, "period": point["period"],
            "filing_type": q.filing_type, "context_id": point["context_id"],
            "source_file": point["source_file"],
        })

    warnings: list[str] = []
    if not q.metrics:
        lines.append("No specific metric was recognized in the question.")
    if facts_included:
        warnings.append(
            "Raw financial_facts values are reported exactly as extracted from the XBRL filing -- "
            "unit/scale is not separately tracked in the database (unlike financial_metrics, which "
            "does carry a unit column). Verify scale against the source filing before using in a "
            "downstream calculation."
        )
    return {"answer": " ".join(lines), "data": data, "sources": sources, "warnings": warnings}


def _handle_trend(q: Classification, bridge: AnalysisBridge) -> dict:
    symbol = q.companies[0]
    analysis = bridge.analyze_trends(symbol, q.filing_type)
    annual_yoy = analysis.get("annual_yoy")
    lines: list[str] = []

    if annual_yoy:
        for field_name in ("revenue_growth_pct", "net_profit_growth_pct", "eps_basic_growth_pct"):
            val = annual_yoy.get(field_name)
            if val is not None:
                lines.append(
                    f"{symbol}'s {field_name.replace('_', ' ')}: {val:+.2f}% "
                    f"({annual_yoy.get('prior_period_end')} -> {annual_yoy.get('latest_period_end')})."
                )
    else:
        lines.append(
            f"No annual year-over-year comparison available yet for {symbol} ({q.filing_type}) -- "
            f"needs at least two annual periods."
        )

    if q.metrics:
        trends = analysis.get("trends") or []
        for metric_key in q.metrics:
            m = metrics_mod.get(metric_key)
            if m.field.endswith("_pct"):
                continue  # growth-of-a-percentage isn't a field analyze() computes
            growth_field = f"{m.field}_growth_pct"
            series = [t[growth_field] for t in trends if t.get(growth_field) is not None]
            if series:
                shown = ", ".join(f"{v:+.2f}%" for v in series[-4:])
                lines.append(f"{m.label} QoQ growth, most recent {min(len(series), 4)} quarter(s): {shown}.")

    return {
        "answer": " ".join(lines) if lines else f"No trend data available for {symbol} ({q.filing_type}).",
        "data": {"annual_yoy": annual_yoy, "trends": analysis.get("trends"), "periods": analysis.get("periods")},
        "sources": [{"type": "data_analysis.analyze", "company": symbol, "filing_type": q.filing_type}],
        "warnings": [],
    }


def _handle_comparison(q: Classification, bridge: AnalysisBridge, db_path: str) -> dict:
    symbols = q.companies if len(q.companies) >= 2 else list(dict.fromkeys(q.companies + _default_universe(db_path)))
    metric_keys = q.metrics or metrics_mod.DEFAULT_COMPARISON_METRICS
    metric_defs = [metrics_mod.get(k) for k in metric_keys]
    usable = [(k, m) for k, m in zip(metric_keys, metric_defs) if m.table == "financial_metrics"]
    skipped = [m for k, m in zip(metric_keys, metric_defs) if m.table != "financial_metrics"]

    result = bridge.compare_peers(symbols, [m.field for _, m in usable], q.filing_type)

    lines: list[str] = []
    for _, m in usable:
        entry = result.get(m.field, {})
        if entry.get("leader"):
            lines.append(
                f"{m.label}: leader is {entry['leader']} at {_fmt_value(entry['leader_value'], m.unit_hint)} "
                f"(peer median {_fmt_value(entry.get('sector_median'), m.unit_hint)})."
            )
        elif entry.get("highest"):
            lines.append(
                f"{m.label} (neutral -- not auto-ranked, see caveats): highest is "
                f"{entry['highest']['symbol']} at {_fmt_value(entry['highest']['value'], m.unit_hint)}, "
                f"lowest is {entry['lowest']['symbol']} at {_fmt_value(entry['lowest']['value'], m.unit_hint)}."
            )
        else:
            lines.append(f"{m.label}: no peer in this group had data.")

    warnings: list[str] = []
    if skipped:
        warnings.append(
            "Skipped raw-fact metric(s) not supported by peer comparison (financial_metrics only): "
            + ", ".join(m.label for m in skipped) + "."
        )
    if q.filing_type == "standalone":
        warnings.append(
            "standalone figures are diagnostic only and may be distorted by one-off items "
            "(see data_analysis's own guidance) -- do not treat as equivalent to consolidated."
        )

    return {
        "answer": " ".join(lines),
        "data": result,
        "sources": [{"type": "financial_metrics", "symbols": symbols, "filing_type": q.filing_type,
                      "note": "latest available filing per company per metric"}],
        "warnings": warnings,
    }


def _handle_ranking(q: Classification, bridge: AnalysisBridge, db_path: str) -> dict:
    symbols = q.companies if len(q.companies) >= 2 else list(dict.fromkeys(q.companies + _default_universe(db_path)))
    result = bridge.compute_rankings(symbols, q.filing_type)
    ordered = sorted(
        (s for s in symbols if result.get(s, {}).get("rank") is not None),
        key=lambda s: result[s]["rank"],
    )
    lines = [f"#{result[s]['rank']} {s} (composite {result[s]['composite_score']})" for s in ordered]
    return {
        "answer": f"Ranking ({q.filing_type}): " + "; ".join(lines) if lines else
                  "No company in this group had enough data to compute a composite score.",
        "data": result,
        "sources": [{"type": "financial_metrics", "symbols": symbols, "filing_type": q.filing_type,
                      "note": "composite = equal-weighted percentile average across 4 categories, "
                              "see data_analysis/src/analysis/ranking.py"}],
        "warnings": [],
    }


def _handle_financial_health(q: Classification, bridge: AnalysisBridge) -> dict:
    symbol = q.companies[0]
    result = bridge.compute_financial_health(symbol, q.filing_type)
    p = result["piotroski"]
    a = result["altman_z_partial"]
    lines = [
        f"{symbol} Piotroski F-Score: {p['score']}/{p['max_possible_score']} "
        f"(of 8 intended criteria; Delta Gross Margin permanently excluded, see caveats)."
    ]
    if a.get("partial_z") is not None:
        lines.append(
            f"Altman partial-Z (X1/X3/X4 only, informational -- official thresholds do NOT apply): "
            f"{a['partial_z']}."
        )
    return {
        "answer": " ".join(lines),
        "data": result,
        "sources": [{"type": "data_analysis.compute_financial_health", "company": symbol,
                      "filing_type": q.filing_type}],
        "warnings": [],
        "caveats": [
            "Piotroski is 8 of 9 criteria -- Delta Gross Margin excluded (no clean COGS tag for "
            "Ind AS IT-services filings), NOT scored as failing.",
            "Altman partial_z uses only X1/X3/X4 -- NOT the official Z''-Score, and its published "
            "2.6/1.1 thresholds do not apply.",
        ],
    }


def _handle_report(q: Classification, bridge: AnalysisBridge, db_path: str) -> dict:
    symbol = q.companies[0]
    peers = q.companies[1:] or [s for s in _default_universe(db_path) if s != symbol]
    result = bridge.compute_company_report(symbol, peers, q.filing_type)
    ranking = result.get("ranking") or {}
    lines = [f"Full report generated for {result['company']['name']} ({symbol}, {q.filing_type})."]
    if ranking:
        lines.append(
            f"Composite ranking: #{ranking.get('rank')} of {len(result.get('peer_symbols', [])) + 1} "
            f"(score {ranking.get('composite_score')})."
        )
    lines.append(f"{len(result.get('flags', []))} flag(s) raised -- see data['flags'].")
    return {
        "answer": " ".join(lines),
        "data": result,
        "sources": [{"type": "data_analysis.compute_company_report", "company": symbol,
                      "filing_type": q.filing_type,
                      "canonical_files": result.get("data_sources", {}).get("canonical_files")}],
        "warnings": [],
        "caveats": result.get("caveats", []),
    }


def _llm_unavailable_reason(llm_status: str, no_chunks: bool = False) -> str:
    if llm_status == "rejected_numeric":
        return (
            "an LLM-written answer was generated but rejected: it used a number that does not "
            "appear in any cited source passage -- a possible digit hallucination"
        )
    if llm_status == "rejected_unit":
        return (
            "an LLM-written answer was generated but rejected: it used a currency unit (e.g. "
            "million/crore/lakh) that does not appear anywhere in the cited source passages -- "
            "a possible unit hallucination"
        )
    if no_chunks:
        return "no relevant source passages were retrieved for the LLM to synthesize from"
    return "Stage 11's LLM router is unreachable, has no configured API key, or its call budget is exhausted"


def _handle_narrative(q: Classification, question: str, rag: RagBridge, k: int = 5) -> dict:
    company = q.companies[0] if len(q.companies) == 1 else None

    expansions = query_expansion.expand_narrative_query(question, q.metrics)
    if expansions:
        results = rag.expanded_retrieve(question, expansions, k=k, company=company)
    else:
        results = rag.reranked_retrieve(question, k=k, company=company)

    if not results:
        return {
            "answer": (
                "No relevant passages were found in the ingested filings for this question"
                + (f" (scoped to {company})" if company else "") + "."
            ),
            "data": {
                "chunks": [], "query_variants_used": expansions,
                "llm_synthesis_used": False, "llm_synthesis_status": "unavailable",
            },
            "sources": [],
            "warnings": [
                "This means either nothing relevant has been ingested yet, or the query needs "
                "rephrasing -- RAG never fabricates an answer when retrieval comes back empty."
            ],
        }

    sources = [
        {"type": "document_chunk", "company": r["company"], "title": r["title"], "source": r["source"],
         "period": r["period"], "page_start": r["page_start"], "page_end": r["page_end"],
         "section": r["section"], "local_path": r["local_path"]}
        for r in results
    ]
    passages = "\n\n".join(
        f"[{i + 1}] ({r['company']}, {r.get('title', '')}, p{r.get('page_start')}-{r.get('page_end')}, "
        f"section={r.get('section')}):\n{r['text'][:500]}"
        for i, r in enumerate(results)
    )


    llm_answer, llm_status = llm_integration.synthesize_narrative_answer(question, results)
    caveats: list[str] = []
    if llm_answer:
        answer = llm_answer
        llm_used = True
        caveats.append(
            "This answer was written by an LLM (Stage 11) strictly from the numbered source "
            "passages in data['chunks'] -- it is an interpretation layer over already-verified "
            "retrieval, not a new source of truth. Verify any specific claim against the cited "
            "passage before relying on it."
        )
    else:
 
        reason = _llm_unavailable_reason(llm_status)
        answer = (
            f"No LLM synthesis is available for this run ({reason}) -- below are the {len(results)} "
            f"most relevant source passages, ranked by relevance, for a human (or a retried LLM call) "
            f"to read and answer from directly:\n\n{passages}"
        )
        llm_used = False

    return {
        "answer": answer,
        "data": {
            "chunks": results, "query_variants_used": expansions,
            "llm_synthesis_used": llm_used, "llm_synthesis_status": llm_status,
        },
        "sources": sources,
        "warnings": [],
        "caveats": caveats,
    }


def _handle_complex(q: Classification, question: str, analysis_bridge: AnalysisBridge,
                     rag: RagBridge, db_path: str) -> dict:
    parts: dict = {}
    sources: list[dict] = []
    warnings: list[str] = []

    if q.companies and q.metrics:
        numeric = _handle_numeric_fact(q, db_path)
        parts["numeric"] = numeric
        sources += numeric["sources"]
        warnings += numeric["warnings"]
    if len(q.companies) >= 2:
        comparison = _handle_comparison(q, analysis_bridge, db_path)
        parts["comparison"] = comparison
        sources += comparison["sources"]
        warnings += comparison["warnings"]
    if q.companies:
        trend = _handle_trend(q, analysis_bridge)
        parts["trend"] = trend
        sources += trend["sources"]

    narrative = _handle_narrative(q, question, rag)
    parts["narrative"] = narrative
    sources += narrative["sources"]
    warnings += narrative["warnings"]

    numeric_summary = " ".join(p["answer"] for key, p in parts.items() if key != "narrative" and p.get("answer"))
    chunks = narrative["data"].get("chunks") or []


    if chunks:
        llm_answer, llm_status = llm_integration.synthesize_complex_answer(question, numeric_summary, chunks)
    else:
        llm_answer, llm_status = None, "unavailable"
    if llm_answer:
        answer = (numeric_summary + "\n\n" if numeric_summary else "") + llm_answer
        caveats = [
            "The qualitative portion of this answer was written by an LLM (Stage 11) from the "
            "numbered source passages in data['narrative']['chunks'] and the verified numeric "
            "findings above -- verify any specific claim against the cited passage before relying "
            "on it."
        ]
    else:

        reason = _llm_unavailable_reason(llm_status, no_chunks=not chunks)
        answer = (
            (numeric_summary + "\n\n" if numeric_summary else "")
            + f"No LLM synthesis is available for this run ({reason}), so the qualitative 'why' part "
              "of this question is answered by the retrieved source passages below rather than a "
              f"written explanation:\n\n{parts['narrative']['answer']}"
        )
        caveats = [
            "LLM synthesis was not available for this answer -- see data['narrative']['chunks'] for "
            "the raw retrieved passages a human (or a retried LLM call) can read directly."
        ]

    parts["llm_synthesis_status"] = llm_status
    return {"answer": answer, "data": parts, "sources": sources, "warnings": warnings, "caveats": caveats}


def _handle_unknown(q: Classification) -> dict:
    lines = ["Could not confidently classify this question."]
    if q.companies:
        lines.append(f"Recognized compan{'y' if len(q.companies) == 1 else 'ies'}: {', '.join(q.companies)}.")
    if q.metrics:
        lines.append(f"Recognized metric(s): {', '.join(metrics_mod.get(k).label for k in q.metrics)}.")
    lines.append(
        "Try rephrasing with an explicit metric (e.g. 'ROE', 'revenue', 'dividend'), an intent word "
        "('compare', 'rank', 'why', 'trend', 'financial health', 'report'), or both."
    )
    lines.extend(q.notes)
    return {"answer": " ".join(lines), "data": {}, "sources": [], "warnings": []}


def answer_question(
    question: str,
    db_path: str = str(DB_PATH),
    analysis_bridge: AnalysisBridge | None = None,
    rag_bridge: RagBridge | None = None,
    intent_override: str | None = None,
    companies_override: list | None = None,
    metrics_override: list | None = None,
) -> dict:
    q = classify_question(question, db_path)
    if intent_override:
        q.intent = intent_override
    if companies_override is not None:
        q.companies = companies_override
    if metrics_override is not None:
        q.metrics = metrics_override

    owns_analysis_bridge = analysis_bridge is None
    owns_rag_bridge = rag_bridge is None
    analysis_bridge = analysis_bridge or AnalysisBridge(db_path=db_path)
    rag_bridge = rag_bridge or RagBridge(db_path=db_path)

    try:
        if q.intent == INTENT_NUMERIC_FACT:
            handled = _handle_numeric_fact(q, db_path)
        elif q.intent == INTENT_TREND:
            handled = _handle_trend(q, analysis_bridge)
        elif q.intent == INTENT_COMPARISON:
            handled = _handle_comparison(q, analysis_bridge, db_path)
        elif q.intent == INTENT_RANKING:
            handled = _handle_ranking(q, analysis_bridge, db_path)
        elif q.intent == INTENT_FINANCIAL_HEALTH:
            handled = _handle_financial_health(q, analysis_bridge)
        elif q.intent == INTENT_REPORT:
            handled = _handle_report(q, analysis_bridge, db_path)
        elif q.intent == INTENT_NARRATIVE:
            handled = _handle_narrative(q, question, rag_bridge)
        elif q.intent == INTENT_COMPLEX:
            handled = _handle_complex(q, question, analysis_bridge, rag_bridge, db_path)
        else:  # INTENT_UNKNOWN, or any override value this module doesn't recognize
            handled = _handle_unknown(q)
    finally:
        if owns_analysis_bridge:
            analysis_bridge.close()
        if owns_rag_bridge:
            rag_bridge.close()

    caveats = handled.get("caveats", [])

    return {
        "question": question,
        "intent": q.intent,
        "classification": {
            "companies": q.companies, "metrics": q.metrics, "filing_type": q.filing_type,
            "matched_keywords": q.matched_keywords, "confidence": q.confidence, "notes": q.notes,
        },
        "answer": handled["answer"],
        "data": handled["data"],
        "sources": handled["sources"],
        "warnings": handled.get("warnings", []),
        "caveats": caveats,
    }
