import subprocess
import tempfile
import unittest
from pathlib import Path

from docuguard.drift_detector import (
    detect_documentation_drift,
    evaluate_finding,
)


class DriftDetectorTests(unittest.TestCase):

    def create_test_repository(self, documentation):
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
            "APPLICATION_DEFAULT_PORT = 8000\n",
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
            "APPLICATION_DEFAULT_PORT = 9000\n",
            encoding="utf-8"
        )

        return temporary_directory, repo

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


if __name__ == "__main__":
    unittest.main()
