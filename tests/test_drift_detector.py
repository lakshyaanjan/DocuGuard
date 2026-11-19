import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from docuguard.llm_client import LLMError
from docuguard.drift_detector import (
    detect_documentation_drift,
    evaluate_finding,
)


class DriftDetectorTests(unittest.TestCase):

    def create_test_repository(
        self,
        documentation,
        old_code="APPLICATION_DEFAULT_PORT = 8000",
        new_code="APPLICATION_DEFAULT_PORT = 9000"
    ):
        """Create an isolated Git repository for a test."""

        temporary_directory = tempfile.TemporaryDirectory()
        repo = Path(temporary_directory.name)

        subprocess.run(
            ["git", "init"],
            cwd=repo,
            check=True,
            capture_output=True
        )

        subprocess.run(
            ["git", "config", "user.name", "DocuGuard Tests"],
            cwd=repo,
            check=True
        )

        subprocess.run(
            ["git", "config", "user.email", "tests@docuguard.local"],
            cwd=repo,
            check=True
        )

        (repo / "sample.py").write_text(
            old_code + "\n",
            encoding="utf-8"
        )

        (repo / "readme.md").write_text(
            documentation,
            encoding="utf-8"
        )

        subprocess.run(
            ["git", "add", "."],
            cwd=repo,
            check=True
        )

        subprocess.run(
            ["git", "commit", "-m", "Initial version"],
            cwd=repo,
            check=True,
            capture_output=True
        )

        # Simulate a code change.
        (repo / "sample.py").write_text(
            new_code + "\n",
            encoding="utf-8"
        )

        return temporary_directory, repo

    def test_required_mode_error_names_supported_provider_keys(self):
        temporary_directory, repo = self.create_test_repository(
            "# Application\nThe application runs on port 8000 by default.\n"
        )
        try:
            with patch("docuguard.llm_client.get_api_key", return_value=None):
                with self.assertRaises(LLMError) as context:
                    detect_documentation_drift(repo, llm_mode="required")
            self.assertIn("GEMINI_API_KEY", str(context.exception))
            self.assertIn("OPENAI_API_KEY", str(context.exception))
        finally:
            temporary_directory.cleanup()

    def test_outdated_documentation_is_flagged(self):
        temporary_directory, repo = self.create_test_repository(
            "# Application\n"
            "The application runs on port 8000 by default.\n"
        )
        try:
            findings = detect_documentation_drift(repo)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["status"], "likely_drift")
        finally:
            temporary_directory.cleanup()

    def test_updated_documentation_is_not_flagged(self):
        temporary_directory, repo = self.create_test_repository(
            "# Application\n"
            "The application runs on port 9000 by default.\n"
        )
        try:
            findings = detect_documentation_drift(repo)
            self.assertEqual(len(findings), 0)
        finally:
            temporary_directory.cleanup()

    def test_historical_documentation_needs_review(self):
        temporary_directory, repo = self.create_test_repository(
            "# Application\n"
            "Previously, the application ran on port 8000 by default.\n"
        )
        try:
            findings = detect_documentation_drift(repo)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["status"], "needs_review")
        finally:
            temporary_directory.cleanup()

    def test_unrelated_port_reference_is_not_flagged(self):
        temporary_directory, repo = self.create_test_repository(
            "# Application\n"
            "The mock SMTP server listens on port 8000 by default.\n"
        )
        try:
            findings = detect_documentation_drift(repo)
            self.assertEqual(len(findings), 0)
        finally:
            temporary_directory.cleanup()

    def test_detects_default_value_with_identifier_in_documentation(self):
        temporary_directory, repo = self.create_test_repository(
            "# Configuration\n"
            "APPLICATION_DEFAULT_PORT is set to 8000.\n"
        )
        try:
            findings = detect_documentation_drift(repo)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["status"], "likely_drift")
            self.assertEqual(findings[0]["old_value"], 8000)
            self.assertEqual(findings[0]["new_value"], 9000)
        finally:
            temporary_directory.cleanup()

    def test_does_not_flag_unrelated_numeric_reference(self):
        temporary_directory, repo = self.create_test_repository(
            "# Network\n"
            "The example HTTP response contains status code 8000.\n"
        )
        try:
            findings = detect_documentation_drift(repo)
            self.assertEqual(len(findings), 0)
        finally:
            temporary_directory.cleanup()

    def test_detects_default_port_without_variable_name(self):
        temporary_directory, repo = self.create_test_repository(
            "# Configuration\n"
            "The service listens on port 8000 by default.\n"
        )
        try:
            findings = detect_documentation_drift(repo)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["status"], "likely_drift")
        finally:
            temporary_directory.cleanup()

    def test_does_not_match_different_service(self):
        temporary_directory, repo = self.create_test_repository(
            "# Network Configuration\n"
            "The SMTP service listens on port 8000 by default.\n"
        )
        try:
            findings = detect_documentation_drift(repo)
            self.assertEqual(len(findings), 0)
        finally:
            temporary_directory.cleanup()

    def test_accepts_application_abbreviation(self):
        temporary_directory, repo = self.create_test_repository(
            "# Network Configuration\n"
            "The APP service listens on port 8000 by default.\n"
        )
        try:
            findings = detect_documentation_drift(repo)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["status"], "likely_drift")
        finally:
            temporary_directory.cleanup()

    def test_does_not_match_http_server(self):
        temporary_directory, repo = self.create_test_repository(
            "# Network Configuration\n"
            "The HTTP server listens on port 8000 by default.\n"
        )
        try:
            findings = detect_documentation_drift(repo)
            self.assertEqual(len(findings), 0)
        finally:
            temporary_directory.cleanup()

    def test_replacement_value_requires_exact_numeric_match(self):
        finding = {
            "old_value": 70,
            "new_value": 80,
            "documentation": {
                "sentence": "The default port is 8000."
            }
        }
        evaluated = evaluate_finding(finding)
        self.assertEqual(evaluated["status"], "likely_drift")

    def test_historical_indicator_uses_word_boundaries(self):
        finding = {
            "old_value": 8000,
            "new_value": 9000,
            "documentation": {
                "sentence": "The application beforehand used port 8000."
            }
        }
        evaluated = evaluate_finding(finding)
        self.assertEqual(evaluated["status"], "likely_drift")

    def test_evaluate_finding_does_not_mutate_input(self):
        finding = {
            "old_value": 8000,
            "new_value": 9000,
            "documentation": {
                "sentence": "The application used port 8000."
            }
        }
        original = {
            "old_value": 8000,
            "new_value": 9000,
            "documentation": {
                "sentence": "The application used port 8000."
            }
        }
        evaluate_finding(finding)
        self.assertEqual(finding, original)

    def test_detects_decimal_default_change(self):
        temporary_directory, repo = self.create_test_repository(
            "# Configuration\nThe application scale factor is 2.5.\n",
            old_code="APPLICATION_SCALE_FACTOR = 2.5",
            new_code="APPLICATION_SCALE_FACTOR = 3.0"
        )
        try:
            findings = detect_documentation_drift(repo)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["old_value"], 2.5)
            self.assertEqual(findings[0]["new_value"], 3.0)
            self.assertEqual(findings[0]["status"], "likely_drift")
        finally:
            temporary_directory.cleanup()

    def test_detects_string_default_change(self):
        temporary_directory, repo = self.create_test_repository(
            "# Configuration\nThe application host is localhost.\n",
            old_code='APPLICATION_HOST = "localhost"',
            new_code='APPLICATION_HOST = "127.0.0.1"'
        )
        try:
            findings = detect_documentation_drift(repo)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["old_value"], "localhost")
            self.assertEqual(findings[0]["new_value"], "127.0.0.1")
            self.assertEqual(findings[0]["status"], "likely_drift")
        finally:
            temporary_directory.cleanup()

    def test_detects_boolean_default_change(self):
        temporary_directory, repo = self.create_test_repository(
            "# Configuration\nThe application feature is enabled: True.\n",
            old_code="APPLICATION_FEATURE_ENABLED = True",
            new_code="APPLICATION_FEATURE_ENABLED = False"
        )
        try:
            findings = detect_documentation_drift(repo)
            self.assertEqual(len(findings), 1)
            self.assertIs(findings[0]["old_value"], True)
            self.assertIs(findings[0]["new_value"], False)
            self.assertEqual(findings[0]["status"], "likely_drift")
        finally:
            temporary_directory.cleanup()

    def test_detects_negative_default_change(self):
        temporary_directory, repo = self.create_test_repository(
            "# Configuration\nThe application timeout is -1 seconds.\n",
            old_code="APPLICATION_TIMEOUT = -1",
            new_code="APPLICATION_TIMEOUT = -2"
        )
        try:
            findings = detect_documentation_drift(repo)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["old_value"], -1)
            self.assertEqual(findings[0]["new_value"], -2)
            self.assertEqual(findings[0]["status"], "likely_drift")
        finally:
            temporary_directory.cleanup()


if __name__ == "__main__":
    unittest.main()
