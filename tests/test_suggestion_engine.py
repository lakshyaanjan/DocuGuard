import unittest

from docuguard.suggestion_engine import generate_suggestion


class SuggestionEngineTests(unittest.TestCase):

    def make_finding(self, old_value, new_value, sentence, confidence=0.99):
        return {
            "status": "likely_drift",
            "old_value": old_value,
            "new_value": new_value,
            "symbol": "SETTING",
            "confidence": confidence,
            "documentation": {
                "sentence": sentence,
                "file": "README.md",
                "line": 5
            },
            "code_change": {
                "file": "sample.py",
                "old_line": 3,
                "new_line": 3
            }
        }

    def test_generates_replacement_suggestion(self):
        finding = self.make_finding(
            "--old-name",
            "--new-name",
            "Use --old-name to launch the application."
        )
        result = generate_suggestion(finding)
        self.assertEqual(result["status"], "suggestion_generated")
        self.assertEqual(
            result["suggested_sentence"],
            "Use --new-name to launch the application."
        )

    def test_removed_flag_requires_manual_review(self):
        finding = self.make_finding(
            "--old-name",
            "<removed>",
            "Use --old-name to launch the application."
        )
        result = generate_suggestion(finding)
        self.assertEqual(result["status"], "manual_review_required")

    def test_does_not_modify_historical_documentation(self):
        finding = self.make_finding(
            "--old-name",
            "--new-name",
            "Previously, --old-name was used."
        )
        finding["status"] = "needs_review"
        result = generate_suggestion(finding)
        self.assertIsNone(result)

    def test_numeric_replacement_does_not_replace_inside_larger_number(self):
        finding = self.make_finding(
            80,
            90,
            "The default port is 8000."
        )
        result = generate_suggestion(finding)
        self.assertEqual(result["status"], "manual_review_required")
        self.assertNotIn("9000", result.get("suggested_sentence", ""))

    def test_replaces_exact_numeric_value(self):
        finding = self.make_finding(
            80,
            90,
            "The default port is 80."
        )
        result = generate_suggestion(finding)
        self.assertEqual(result["status"], "suggestion_generated")
        self.assertEqual(result["suggested_sentence"], "The default port is 90.")

    def test_repeated_value_requires_manual_review(self):
        finding = self.make_finding(
            8000,
            9000,
            "Port 8000 is documented twice: 8000."
        )
        result = generate_suggestion(finding)
        self.assertEqual(result["status"], "manual_review_required")

    def test_low_confidence_requires_manual_review(self):
        finding = self.make_finding(
            8000,
            9000,
            "The service listens on port 8000.",
            confidence=0.75
        )
        result = generate_suggestion(finding)
        self.assertEqual(result["status"], "manual_review_required")


if __name__ == "__main__":
    unittest.main()
