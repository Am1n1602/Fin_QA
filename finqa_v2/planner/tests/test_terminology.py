import unittest

from finqa_v2.planner.terminology import TERMS, expand_lexical_query, semantic_query


class ExpandLexicalQuery(unittest.TestCase):
    def test_no_dictionary_term_mentioned_is_unchanged(self):
        q = "What did the company report about its risk factors?"
        self.assertEqual(expand_lexical_query(q), q)

    def test_expands_only_the_mentioned_term(self):
        out = expand_lexical_query("Why did profits fall?")
        # "profits" alone doesn't match "profit after tax"/"net profit" word-for-word,
        # so use the exact §11 example instead:
        out = expand_lexical_query("Why did net profit fall?")
        self.assertIn("PAT", out)
        self.assertIn("net income", out)
        self.assertNotIn("profit before tax", out)  # PBT's synonym, not mentioned -> not added
        self.assertTrue(out.startswith("Why did net profit fall?"))

    def test_already_present_synonym_not_duplicated(self):
        out = expand_lexical_query("What was PAT and net profit this quarter?")
        self.assertEqual(out.count("net profit"), 1)

    def test_case_insensitive_and_word_boundary(self):
        out = expand_lexical_query("What was the pat for the quarter?")
        self.assertIn("net profit", out)
        # "roe" must not fire inside an unrelated word
        out2 = expand_lexical_query("Compare TCS and Infosys heroes of the industry")
        self.assertEqual(out2, "Compare TCS and Infosys heroes of the industry")

    def test_multiple_mentioned_terms_each_expand(self):
        out = expand_lexical_query("How did ROE and revenue trend this year?")
        self.assertIn("return on equity", out)
        self.assertIn("sales", out)
        self.assertIn("turnover", out)

    def test_acronym_canonical_form_added_when_synonym_mentioned_instead(self):
        out = expand_lexical_query("What was the return on equity in FY2026?")
        self.assertIn("ROE", out)

    def test_dictionary_has_the_section_12_minimum_terms(self):
        for term in ("PAT", "PBT", "EBITDA", "EBIT", "ROE", "ROCE", "NPM", "YoY", "QoQ",
                    "revenue"):
            self.assertIn(term, TERMS, term)


class SemanticQuery(unittest.TestCase):
    def test_returns_question_unchanged(self):
        self.assertEqual(semantic_query("Why did net profit fall?"), "Why did net profit fall?")


if __name__ == "__main__":
    unittest.main()
