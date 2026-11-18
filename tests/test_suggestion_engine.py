
import unittest

from docuguard.suggestion_engine import generate_suggestion


class SuggestionEngineTests(unittest.TestCase):

    def test_generates_replacement_suggestion(self):
        finding = {
            "status": "likely_drift",
            "old_value": "--old-name",
            "new_value": "--new-name",
            "symbol": "--old-name",
            "documentation": {
                "sentence": "Use --old-name to launch the application.",
                "file": "README.md",
                "line": 5
            },
            "code_change": {
                "file": "sample.py",
                "old_line": 3,
                "new_line": 3
            }
        }

        result = generate_suggestion(finding)

        self.assertEqual(result["status"], "suggestion_generated")
        self.assertEqual(
            result["suggested_sentence"],
            "Use --new-name to launch the application."
        )

    def test_removed_flag_requires_manual_review(self):
        finding = {
            "status": "likely_drift",
            "old_value": "--old-name",
            "new_value": "<removed>",
            "symbol": "--old-name",
            "documentation": {
                "sentence": "Use --old-name to launch the application.",
                "file": "README.md",
                "line": 5
            },
            "code_change": {
                "file": "sample.py",
                "old_line": 3,
                "new_line": None
            }
        }

        result = generate_suggestion(finding)

        self.assertEqual(result["status"], "manual_review_required")

    def test_does_not_modify_historical_documentation(self):
        finding = {
            "status": "needs_review",
            "old_value": "--old-name",
            "new_value": "--new-name",
            "symbol": "--old-name",
            "documentation": {
                "sentence": "Previously, --old-name was used.",
                "file": "README.md",
                "line": 5
            },
            "code_change": {
                "file": "sample.py",
                "old_line": 3,
                "new_line": 3
            }
        }

        result = generate_suggestion(finding)

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
