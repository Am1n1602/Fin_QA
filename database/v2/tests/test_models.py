"""Model invariants for database.v2 Stdlib unittest, no deps.

Run:  python -m unittest database.v2.tests.test_models   (from repo root)
"""
from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from datetime import date

from database.v2.models import (
    Basis,
    Company,
    FinancialFact,
    Index,
    IndexMembership,
    MappingConfidence,
    Source,
    StatementType,
)


class TestCompany(unittest.TestCase):
    def test_minimal(self):
        c = Company(name="Tata Consultancy Services", ticker="TCS")
        self.assertEqual(c.exchange.value, "NSE")
        self.assertTrue(c.active)
        self.assertIsNone(c.company_id)

    def test_requires_name_and_ticker(self):
        with self.assertRaises(ValueError):
            Company(name="", ticker="TCS")
        with self.assertRaises(ValueError):
            Company(name="X", ticker="")

    def test_frozen(self):
        c = Company(name="X", ticker="X")
        with self.assertRaises(FrozenInstanceError):
            c.ticker = "Y"  # type: ignore[misc]

    def test_aliases_deduped(self):
        c = Company(name="LTIMindtree", ticker="LTM", aliases=("LTIM", "LTIM"))
        self.assertEqual(c.aliases, ("LTIM",))


class TestIndexMembership(unittest.TestCase):
    def test_open_ended_is_current(self):
        m = IndexMembership(index_id=1, company_id=2)
        self.assertTrue(m.is_current)
        self.assertTrue(m.is_active_on(date(2026, 9, 10)))

    def test_window(self):
        m = IndexMembership(
            index_id=1, company_id=2,
            valid_from=date(2024, 1, 1), valid_to=date(2026, 1, 1),
        )
        self.assertFalse(m.is_active_on(date(2023, 12, 31)))
        self.assertTrue(m.is_active_on(date(2024, 1, 1)))       # inclusive
        self.assertTrue(m.is_active_on(date(2025, 6, 1)))
        self.assertFalse(m.is_active_on(date(2026, 1, 1)))      # exclusive
        self.assertFalse(m.is_current)


class TestFinancialFact(unittest.TestCase):
    def _fact(self, **kw):
        base = dict(
            company_id=1, metric="revenue", value=100.0, unit="INR",
            statement_type=StatementType.PROFIT_AND_LOSS, basis=Basis.CONSOLIDATED,
        )
        base.update(kw)
        return FinancialFact(**base)

    def test_enums_coerced_from_str(self):
        f = FinancialFact(
            company_id=1, metric="roe", value=15.0, unit="pct",
            statement_type="profit_and_loss", basis="consolidated",
        )
        self.assertIs(f.statement_type, StatementType.PROFIT_AND_LOSS)
        self.assertIs(f.basis, Basis.CONSOLIDATED)

    def test_missing_value_is_first_class(self):
        f = self._fact(value=None, mapping_confidence=MappingConfidence.UNMAPPED,
                       mapping_reason="no clean COGS tag for Ind AS IT-services filings")
        self.assertTrue(f.is_missing)
        self.assertEqual(f.problems(), [])

    def test_missing_value_without_reason_is_flagged(self):
        f = self._fact(value=None, mapping_confidence=MappingConfidence.UNMAPPED)
        self.assertIn("mapping_reason", " ".join(f.problems()))

    def test_bad_quarter_rejected(self):
        with self.assertRaises(ValueError):
            self._fact(quarter=5)

    def test_zero_is_a_real_value_not_missing(self):
        f = self._fact(value=0.0)
        self.assertFalse(f.is_missing)


class TestSource(unittest.TestCase):
    def test_requires_kind(self):
        with self.assertRaises(ValueError):
            Source(kind="")

    def test_ok(self):
        s = Source(kind="xbrl", company_id=1, content_hash="abc")
        self.assertEqual(s.kind, "xbrl")


class TestIndex(unittest.TestCase):
    def test_requires_name(self):
        with self.assertRaises(ValueError):
            Index(name="")


if __name__ == "__main__":
    unittest.main()
