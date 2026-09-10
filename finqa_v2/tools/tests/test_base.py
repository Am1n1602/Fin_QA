"""Tool primitives: validation / timing / error capture / trace."""
from __future__ import annotations

import unittest

from pydantic import BaseModel, Field

from finqa_v2.tools.base import Tool, ToolRegistry


class _In(BaseModel):
    x: int = Field(..., ge=0)
    y: int = 1


class TestTool(unittest.TestCase):
    def test_ok_with_evidence_tuple(self):
        t = Tool("add", "adds", _In, lambda m: ({"sum": m.x + m.y}, [{"evidence_id": "e1"}]))
        r = t.call(x=2, y=3)
        self.assertTrue(r.ok)
        self.assertEqual(r.value, {"sum": 5})
        self.assertEqual(r.evidence, ({"evidence_id": "e1"},))
        self.assertGreaterEqual(r.latency_ms, 0.0)

    def test_ok_plain_value(self):
        t = Tool("id", "", _In, lambda m: m.x)
        r = t.call(x=7)
        self.assertTrue(r.ok)
        self.assertEqual(r.value, 7)
        self.assertEqual(r.evidence, ())

    def test_validation_error(self):
        t = Tool("v", "", _In, lambda m: m.x)
        r = t.call(x=-1)
        self.assertFalse(r.ok)
        self.assertIn("invalid input", r.error)

    def test_missing_required(self):
        t = Tool("v", "", _In, lambda m: m.x)
        r = t.call(y=2)
        self.assertFalse(r.ok)
        self.assertIn("x", r.error)

    def test_fn_exception_captured(self):
        def boom(m):
            raise ValueError("nope")

        r = Tool("b", "", _In, boom).call(x=1)
        self.assertFalse(r.ok)
        self.assertIn("ValueError: nope", r.error)

    def test_schema_shape(self):
        s = Tool("s", "desc", _In, lambda m: m.x).schema()
        self.assertEqual(s["name"], "s")
        self.assertEqual(s["description"], "desc")
        self.assertIn("properties", s["parameters"])
        self.assertIn("x", s["parameters"]["properties"])


class TestRegistry(unittest.TestCase):
    def _reg(self):
        reg = ToolRegistry()
        reg.add("add", "", _In, lambda m: {"sum": m.x + m.y})
        reg.add("boom", "", _In, lambda m: (_ for _ in ()).throw(RuntimeError("x")))
        return reg

    def test_call_and_trace(self):
        reg = self._reg()
        reg.call("add", x=1, y=2)
        reg.call("boom", x=1)
        reg.call("nonexistent", x=1)
        self.assertEqual(len(reg.trace), 3)
        s = reg.trace_summary()
        self.assertEqual(s["n_calls"], 3)
        self.assertEqual(s["errors"], 2)
        self.assertEqual(s["by_tool"]["add"], 1)

    def test_unknown_tool(self):
        r = ToolRegistry().call("ghost")
        self.assertFalse(r.ok)
        self.assertIn("unknown tool", r.error)

    def test_schemas_json_safe(self):
        import json
        json.dumps(self._reg().schemas())

    def test_reset_trace(self):
        reg = self._reg()
        reg.call("add", x=1)
        reg.reset_trace()
        self.assertEqual(reg.trace, [])


if __name__ == "__main__":
    unittest.main()
