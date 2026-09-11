"""finqa_v2/observability/logging_config.py -- request-id correlation + JSON formatting."""
from __future__ import annotations

import json
import logging
import unittest

from finqa_v2.observability.logging_config import (
    JsonFormatter,
    RequestIdFilter,
    new_request_id,
    request_id_var,
)


def _make_record(msg: str = "hello") -> logging.LogRecord:
    return logging.LogRecord("test.logger", logging.INFO, __file__, 1, msg, (), None)


class TestNewRequestId(unittest.TestCase):
    def test_unique_and_hex(self):
        a, b = new_request_id(), new_request_id()
        self.assertNotEqual(a, b)
        int(a, 16)  # raises ValueError if not hex
        self.assertEqual(len(a), 16)


class TestRequestIdFilter(unittest.TestCase):
    def test_attaches_current_context_value(self):
        token = request_id_var.set("req-abc123")
        try:
            record = _make_record()
            self.assertTrue(RequestIdFilter().filter(record))
            self.assertEqual(record.request_id, "req-abc123")
        finally:
            request_id_var.reset(token)

    def test_default_outside_a_request(self):
        record = _make_record()
        RequestIdFilter().filter(record)
        self.assertEqual(record.request_id, "-")


class TestJsonFormatter(unittest.TestCase):
    def test_produces_valid_json_with_expected_keys(self):
        record = _make_record("something happened")
        record.request_id = "req-xyz"
        line = JsonFormatter().format(record)
        payload = json.loads(line)
        self.assertEqual(payload["message"], "something happened")
        self.assertEqual(payload["request_id"], "req-xyz")
        self.assertEqual(payload["level"], "INFO")
        self.assertIn("ts", payload)

    def test_includes_exception_info(self):
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = logging.LogRecord("t", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
        record.request_id = "-"
        payload = json.loads(JsonFormatter().format(record))
        self.assertIn("ValueError: boom", payload["exc_info"])


if __name__ == "__main__":
    unittest.main()
