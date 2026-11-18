import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docuguard.reporting import (
    render_html_report,
    render_markdown_summary,
    write_github_annotations,
    write_json_report,
    write_step_summary,
)


def sample_finding():
    return {
        "status": "likely_drift",
        "symbol": "DEFAULT_PORT",
        "old_value": 8000,
        "new_value": 9000,
        "confidence": 0.95,
        "reason": "The documentation retains the old default.",
        "documentation": {
            "file": "README.md",
            "line": 8,
            "sentence": "The app <script>alert(1)</script> listens on port 8000."
        },
        "code_change": {
            "file": "settings.py",
            "old_line": 3,
            "new_line": 3
        }
    }


class ReportingTests(unittest.TestCase):

    def test_markdown_summary_contains_both_source_locations(self):
        finding = sample_finding()
        summary = render_markdown_summary([finding], [])
        self.assertIn("README.md:8", summary)
        self.assertIn("settings.py:3", summary)
        self.assertIn("likely_drift", summary)

    def test_html_report_escapes_documentation_content(self):
        finding = sample_finding()
        report = render_html_report([finding], [], "test-repo")
        self.assertIn("&lt;script&gt;", report)
        self.assertNotIn("<script>alert(1)</script>", report)
        self.assertIn("test-repo", report)

    def test_empty_report_has_success_message(self):
        report = render_html_report([], [], "test-repo")
        self.assertIn("No documentation drift detected", report)

    def test_json_report_is_written(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            write_json_report(path, [sample_finding()], [])
            self.assertIn("README.md", path.read_text(encoding="utf-8"))

    def test_step_summary_is_written_when_environment_is_set(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.md"
            with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(path)}):
                self.assertTrue(write_step_summary("# Summary"))
            self.assertEqual(path.read_text(encoding="utf-8"), "# Summary\n")

    def test_annotations_include_document_path_and_line(self):
        finding = sample_finding()
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            with patch("builtins.print") as mocked_print:
                write_github_annotations([finding])
        output = mocked_print.call_args.args[0]
        self.assertIn("file=README.md", output)
        self.assertIn("line=8", output)
        self.assertTrue(output.startswith("::warning"))


if __name__ == "__main__":
    unittest.main()
