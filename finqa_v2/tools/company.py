"""Company tools (§19): get_company, get_peers, get_index_members."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class _Company(BaseModel):
    ticker: str


class _Peers(BaseModel):
    ticker: str
    limit: int = Field(15, ge=1, le=60)


class _IndexMembers(BaseModel):
    index_name: str = "NIFTY 50"
    on: str | None = Field(None, description="ISO date; omit for current members")


def _co_dict(c) -> dict:
    return {
        "company_id": c.company_id, "name": c.name, "ticker": c.ticker,
        "exchange": c.exchange.value, "isin": c.isin, "sector": c.sector,
        "industry": c.industry, "active": c.active, "aliases": list(c.aliases),
    }


def register(reg, repos) -> None:
    def _company(m: _Company):
        c = repos.companies.resolve(m.ticker)
        if c is None:
            raise LookupError(f"unknown company {m.ticker!r}")
        return _co_dict(c)

    def _peers(m: _Peers):
        c = repos.companies.resolve(m.ticker)
        if c is None:
            raise LookupError(f"unknown company {m.ticker!r}")
        peers = [p for p in repos.companies.list(active=True, sector=c.sector)
                 if p.company_id != c.company_id][: m.limit]
        return {"ticker": c.ticker, "sector": c.sector,
                "peers": [_co_dict(p) for p in peers]}

    def _members(m: _IndexMembers):
        idx = repos.indices.get_by_name(m.index_name)
        if idx is None:
            raise LookupError(f"unknown index {m.index_name!r}")
        on = date.fromisoformat(m.on) if m.on else None
        members = repos.indices.members(idx.index_id, on=on)
        return {"index": idx.name, "on": m.on, "count": len(members),
                "members": [_co_dict(c) for c in members]}

    reg.add("get_company", "Company profile: name, ticker, ISIN, sector, aliases, active flag.",
            _Company, _company)
    reg.add("get_peers", "Same-sector active companies for a given company.",
            _Peers, _peers)
    reg.add("get_index_members", "Members of an index (default NIFTY 50), current or as-of a date.",
            _IndexMembers, _members)
