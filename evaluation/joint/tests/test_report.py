import json
import tempfile
import unittest
from pathlib import Path

from evaluation.joint.report import build_row, render_table


def _retrieval_json(tmp: Path, *, recall5=0.5, mrr=0.3, ndcg5=0.25, p50=20.0) -> Path:
    p = tmp / "retrieval.json"
    p.write_text(json.dumps({
        "results": {"hybrid": {"recall@5": recall5, "mrr": mrr, "ndcg@5": ndcg5, "p50_ms": p50}}
    }), encoding="utf-8")
    return p


def _answer_json(tmp: Path, *, correctness=0.8, grounded=0.9, citation_f1=0.0,
                 abstention=0.95, p50=1.5, p95=100.0) -> Path:
    p = tmp / "answer.json"
    p.write_text(json.dumps({
        "aggregates": {
            "correctness": {"accuracy": correctness},
            "groundedness": {"verdict": {"accuracy": grounded}},
            "citation": {"mean_f1": citation_f1},
            "abstention": {"accuracy": abstention},
            "operations": {"latency_ms": {"p50": p50, "p95": p95}},
        }
    }), encoding="utf-8")
    return p


class BuildRow(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)

    def test_pulls_retrieval_metrics_from_the_hybrid_mode(self):
        retrieval = _retrieval_json(self.tmp, recall5=0.5061, mrr=0.3293, ndcg5=0.3032, p50=31.9)
        answer = _answer_json(self.tmp)
        row = build_row("current production", retrieval, answer)
        self.assertEqual(row["recall@5"], 0.5061)
        self.assertEqual(row["mrr"], 0.3293)
        self.assertEqual(row["ndcg@5"], 0.3032)
        self.assertEqual(row["retrieval_p50_ms"], 31.9)

    def test_pulls_answer_quality_metrics_from_aggregates(self):
        retrieval = _retrieval_json(self.tmp)
        answer = _answer_json(self.tmp, correctness=0.8372, grounded=1.0, citation_f1=0.0, abstention=0.9792)
        row = build_row("x", retrieval, answer)
        self.assertEqual(row["answer_accuracy"], 0.8372)
        self.assertEqual(row["groundedness"], 1.0)
        self.assertEqual(row["citation_f1"], 0.0)
        self.assertEqual(row["abstention_accuracy"], 0.9792)

    def test_label_is_preserved_verbatim(self):
        row = build_row("v2.0 baseline", _retrieval_json(self.tmp), _answer_json(self.tmp))
        self.assertEqual(row["configuration"], "v2.0 baseline")

    def test_sources_are_recorded_for_reproducibility(self):
        retrieval = _retrieval_json(self.tmp)
        answer = _answer_json(self.tmp)
        row = build_row("x", retrieval, answer)
        self.assertEqual(row["_sources"]["retrieval_report"], str(retrieval))
        self.assertEqual(row["_sources"]["answer_report"], str(answer))


class RenderTable(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)

    def test_header_and_separator_and_one_row_per_input(self):
        rows = [build_row("a", _retrieval_json(self.tmp), _answer_json(self.tmp)),
                build_row("b", _retrieval_json(self.tmp), _answer_json(self.tmp))]
        table = render_table(rows)
        lines = table.splitlines()
        self.assertEqual(len(lines), 4)   # header + separator + 2 rows
        self.assertIn("configuration", lines[0])
        self.assertIn("recall@5", lines[0])

    def test_empty_rows_still_renders_a_header(self):
        table = render_table([])
        self.assertEqual(len(table.splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
