import subprocess
import tempfile
import unittest
from pathlib import Path

from docuguard.drift_detector import detect_documentation_drift
from docuguard.suggestion_engine import generate_suggestion


class ConfigurationOptionTests(unittest.TestCase):

    def create_repository(self, code_before, code_after, docs):
        temporary_directory = tempfile.TemporaryDirectory()
        repo = Path(temporary_directory.name)
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "DocuGuard Tests"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "tests@docuguard.local"], cwd=repo, check=True)
        (repo / "settings.py").write_text(code_before + "\n", encoding="utf-8")
        (repo / "README.md").write_text(docs, encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "Initial config"], cwd=repo, check=True, capture_output=True)
        (repo / "settings.py").write_text(code_after + "\n", encoding="utf-8")
        return temporary_directory, repo

    def test_added_dictionary_option_missing_from_table_is_flagged(self):
        docs = "# APP_CONFIG\n\n| Option | Default |\n|---|---|\n| host | localhost |\n"
        temp, repo = self.create_repository(
            'APP_CONFIG = {"host": "localhost"}',
            'APP_CONFIG = {"host": "localhost", "timeout": 30}',
            docs
        )
        try:
            findings = detect_documentation_drift(repo)
            matches = [x for x in findings if x.get("drift_type") == "configuration_option_added"]
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["option"], "timeout")
            self.assertEqual(matches[0]["option_default"], 30)
            self.assertEqual(matches[0]["status"], "likely_drift")
            self.assertEqual(matches[0]["documentation"]["file"], "README.md")
            suggestion = generate_suggestion(matches[0])
            self.assertEqual(suggestion["status"], "manual_review_required")
            self.assertIn("Add this option", suggestion["reason"])
        finally:
            temp.cleanup()

    def test_added_dictionary_option_already_documented_is_not_flagged(self):
        docs = (
            "# APP_CONFIG\n\n| Option | Default |\n|---|---|\n"
            "| host | localhost |\n| timeout | 30 |\n"
        )
        temp, repo = self.create_repository(
            'APP_CONFIG = {"host": "localhost"}',
            'APP_CONFIG = {"host": "localhost", "timeout": 30}',
            docs
        )
        try:
            findings = detect_documentation_drift(repo)
            self.assertFalse(any(x.get("drift_type") == "configuration_option_added" for x in findings))
        finally:
            temp.cleanup()

    def test_removed_dictionary_option_still_documented_is_flagged(self):
        docs = (
            "# APP_CONFIG\n\n| Option | Default |\n|---|---|\n"
            "| host | localhost |\n| timeout | 30 |\n"
        )
        temp, repo = self.create_repository(
            'APP_CONFIG = {"host": "localhost", "timeout": 30}',
            'APP_CONFIG = {"host": "localhost"}',
            docs
        )
        try:
            findings = detect_documentation_drift(repo)
            matches = [x for x in findings if x.get("drift_type") == "configuration_option_removed"]
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["option"], "timeout")
            self.assertEqual(matches[0]["status"], "likely_drift")
            self.assertEqual(generate_suggestion(matches[0])["status"], "manual_review_required")
        finally:
            temp.cleanup()

    def test_changed_dictionary_default_is_reported_and_suggested(self):
        docs = (
            "# APP_CONFIG\n\n| Option | Default |\n|---|---|\n"
            "| host | localhost |\n"
        )
        temp, repo = self.create_repository(
            'APP_CONFIG = {"host": "localhost"}',
            'APP_CONFIG = {"host": "127.0.0.1"}',
            docs
        )
        try:
            findings = detect_documentation_drift(repo)
            matches = [x for x in findings if x.get("drift_type") == "configuration_value_changed"]
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]["status"], "likely_drift")
            suggestion = generate_suggestion(matches[0])
            self.assertEqual(suggestion["status"], "suggestion_generated")
            self.assertEqual(suggestion["suggested_sentence"], "| host | 127.0.0.1 |")
        finally:
            temp.cleanup()


if __name__ == "__main__":
    unittest.main()
