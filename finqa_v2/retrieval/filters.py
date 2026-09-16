"""Metadata pre-filter (§16). A filter dict maps chunk-metadata keys to an allowed
scalar or an iterable of allowed values:

    {"company_id": 3, "section": ["notes", "segment_information"], "financial_year": 2026}
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

_KEYS = ("company_id", "financial_year", "document_type", "section", "segment", "topic")


def _allowed(spec: Any) -> set:
    if spec is None:
        return set()
    if isinstance(spec, (str, bytes)) or not isinstance(spec, Iterable):
        return {spec}
    return set(spec)


def compile_filter(filters: Mapping[str, Any] | None):
    if not filters:
        return lambda meta: True
    checks = [(k, _allowed(v)) for k, v in filters.items() if k in _KEYS and v is not None]
    if not checks:
        return lambda meta: True

    def _match(meta: Mapping[str, Any]) -> bool:
        return all(meta.get(k) in allowed for k, allowed in checks)

    return _match
