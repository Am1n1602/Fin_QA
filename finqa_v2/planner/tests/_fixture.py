"""In-memory repos with a handful of real NIFTY-50 companies for planner tests."""
from __future__ import annotations

from finqa_v2.models import Company

_COMPANIES = [
    ("Tata Consultancy Services", "TCS", "IT"),
    ("Infosys", "INFY", "IT"),
    ("HCL Technologies", "HCLTECH", "IT"),
    ("Wipro", "WIPRO", "IT"),
    ("Reliance Industries Ltd.", "RELIANCE", "Oil Gas & Consumable Fuels"),
    ("HDFC Bank Ltd.", "HDFCBANK", "Financial Services"),
    ("ICICI Bank Ltd.", "ICICIBANK", "Financial Services"),
    ("Bajaj Finance Ltd.", "BAJFINANCE", "Financial Services"),
    ("Bajaj Finserv Ltd.", "BAJAJFINSV", "Financial Services"),
    ("ITC Ltd.", "ITC", "Fast Moving Consumer Goods"),
]


def seed(repos):
    for name, ticker, sector in _COMPANIES:
        repos.companies.upsert(Company(name=name, ticker=ticker, sector=sector))
    repos.commit()
