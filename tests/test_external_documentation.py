import subprocess
import tempfile
import unittest
from pathlib import Path

from docuguard.drift_detector import detect_documentation_drift


class ExternalDocumentationTests(unittest.TestCase):

    def test_analyses_documentation_from_a_separate_checkout(self):
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as docs_dir:
            source = Path(source_dir)
            docs = Path(docs_dir)

            subprocess.run(["git", "init"], cwd=source, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "DocuGuard Tests"], cwd=source, check=True)
            subprocess.run(["git", "config", "user.email", "tests@docuguard.local"], cwd=source, check=True)

            (source / "settings.py").write_text("APPLICATION_DEFAULT_PORT = 8000\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=source, check=True)
            subprocess.run(["git", "commit", "-m", "Initial source"], cwd=source, check=True, capture_output=True)

            (source / "settings.py").write_text("APPLICATION_DEFAULT_PORT = 9000\n", encoding="utf-8")
            (docs / "README.md").write_text(
                "The application runs on port 8000 by default.\n",
                encoding="utf-8"
            )

            findings = detect_documentation_drift(source, docs)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["status"], "likely_drift")
            self.assertEqual(findings[0]["documentation"]["file"], "README.md")


if __name__ == "__main__":
    unittest.main()
