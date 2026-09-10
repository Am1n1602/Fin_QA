"""Share-price CSV import + the SharePriceRepository."""
from __future__ import annotations

import unittest
from datetime import date

from finqa_v2.models import Company
from finqa_v2.prices.import_prices import import_prices_file
from finqa_v2.sqlite import SqliteRepositories

_CSV = (
    "DATE,SERIES,OPEN,HIGH,LOW,PREV. CLOSE,LTP,CLOSE,VWAP,VOLUME,VALUE,NO OF TRADES,"
    "DELIVERY QTY,DELIVERY %,SYMBOL\n"
    "2026-03-30 18:30:00,EQ,100,105,99,101,103,104.5,102.7,1000,0,50,0,0,TESTCO\n"
    "2026-03-27 18:30:00,EQ,98,101,97,99,100,100.0,99.5,900,0,40,0,0,TESTCO\n"
    "2026-03-27 18:30:00,EQ,98,101,97,99,100,100.0,99.5,900,0,40,0,0,TESTCO\n"  # dup date
    ",EQ,,,,,,,,,,,,,TESTCO\n"                                                   # junk row
)


class TestImport(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        self.repos.companies.upsert(Company(name="Testco", ticker="TESTCO"))
        self.repos.commit()

    def _write(self, tmp_path):
        p = tmp_path / "TESTCO_prices.csv"
        p.write_text(_CSV, encoding="utf-8")
        return p

    def test_import_and_dedup(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            p = self._write(Path(d))
            res = import_prices_file(p, self.repos)
            self.repos.commit()
        self.assertEqual(res["written"], 2)                 # dup date + junk row dropped
        self.assertEqual(res["date_min"], "2026-03-27")
        co = self.repos.companies.get_by_ticker("TESTCO")
        self.assertEqual(len(self.repos.prices.range(co.company_id)), 2)

    def test_idempotent(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            p = self._write(Path(d))
            import_prices_file(p, self.repos)
            import_prices_file(p, self.repos)              # again -> same rows, one source
            self.repos.commit()
        co = self.repos.companies.get_by_ticker("TESTCO")
        self.assertEqual(len(self.repos.prices.range(co.company_id)), 2)
        n_src = self.repos.connection.execute(
            "SELECT COUNT(*) FROM sources WHERE kind='price_feed'").fetchone()[0]
        self.assertEqual(n_src, 1)

    def test_on_or_before_window(self):
        co = self.repos.companies.get_by_ticker("TESTCO")
        from finqa_v2.models import SharePrice

        self.repos.prices.add_prices([SharePrice(co.company_id, date(2026, 3, 30), 104.5)])
        self.repos.commit()
        self.assertAlmostEqual(
            self.repos.prices.on_or_before(co.company_id, date(2026, 3, 31)).close, 104.5)
        # 2026-03-30 is > 14 days before 2026-05-01 -> no price
        self.assertIsNone(self.repos.prices.on_or_before(co.company_id, date(2026, 5, 1)))

    def test_unknown_company_skipped(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "NOPE_prices.csv"
            p.write_text(_CSV.replace("TESTCO", "NOPE"), encoding="utf-8")
            res = import_prices_file(p, self.repos)
        self.assertIn("skipped", res)


if __name__ == "__main__":
    unittest.main()
