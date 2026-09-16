import unittest

from finqa_v2.api.sanitize import strip_server_paths


class StripServerPaths(unittest.TestCase):
    def test_removes_top_level_uri(self):
        self.assertEqual(strip_server_paths({"uri": "/srv/x.pdf", "title": "t"}), {"title": "t"})

    def test_removes_nested_uri_in_dicts_and_lists(self):
        obj = {"sources": [{"citation_id": "c1", "uri": "/srv/a.pdf"},
                           {"citation_id": "c2", "uri": None}],
              "graph": {"nodes": [{"id": "n1", "type": "source", "uri": "/srv/b.pdf"}]}}
        out = strip_server_paths(obj)
        self.assertNotIn("uri", out["sources"][0])
        self.assertNotIn("uri", out["sources"][1])
        self.assertNotIn("uri", out["graph"]["nodes"][0])
        self.assertEqual(out["sources"][0]["citation_id"], "c1")

    def test_leaves_everything_else_untouched(self):
        obj = {"a": 1, "b": [1, 2, {"c": "manufacturing"}], "d": None, "e": True}
        self.assertEqual(strip_server_paths(obj), obj)

    def test_handles_tuples_like_lists(self):
        self.assertEqual(strip_server_paths(({"uri": "x", "y": 1},)), [{"y": 1}])

    def test_does_not_touch_text_containing_the_substring_uri(self):
        # "manufacturing" / "restructuring" contain "uri" as a substring -- must survive
        obj = {"text": "Restructuring expenses in Manufacturing segment"}
        self.assertEqual(strip_server_paths(obj), obj)


if __name__ == "__main__":
    unittest.main()
