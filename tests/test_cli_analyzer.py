
import subprocess
import tempfile
import unittest
from pathlib import Path
from docuguard.drift_detector import detect_documentation_drift

from docuguard.cli_analyzer import (
    extract_cli_flags,
    analyze_cli_changes,
)


class TestCLIAnalyzer(unittest.TestCase):

    def test_extracts_cli_flags(self):
        source = '''
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--old-name")
parser.add_argument("-v", "--verbose")
'''

        flags = extract_cli_flags(source)
        names = [item["flag"] for item in flags]

        self.assertIn("--old-name", names)
        self.assertIn("-v", names)
        self.assertIn("--verbose", names)

    def test_detects_renamed_cli_flag(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)

            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)

            sample = repo / "sample.py"
            sample.write_text(
                'import argparse\nparser = argparse.ArgumentParser()\n'
                'parser.add_argument("--old-name")\n',
                encoding="utf-8"
            )

            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "Initial version"], cwd=repo, check=True, capture_output=True)

            sample.write_text(
                'import argparse\nparser = argparse.ArgumentParser()\n'
                'parser.add_argument("--new-name")\n',
                encoding="utf-8"
            )

            changes = analyze_cli_changes(repo)

            self.assertEqual(len(changes), 1)
            self.assertIn("--old-name", [x["flag"] for x in changes[0]["removed_flags"]])
            self.assertIn("--new-name", [x["flag"] for x in changes[0]["added_flags"]])

    def test_detects_outdated_cli_documentation(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)

            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)

            (repo / "sample.py").write_text(
                'import argparse\n'
                'parser = argparse.ArgumentParser()\n'
                'parser.add_argument("--old-name")\n',
                encoding="utf-8"
            )

            (repo / "README.md").write_text(
                "Use the --old-name option to launch the application.\n",
                encoding="utf-8"
            )

            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "Initial version"], cwd=repo, check=True, capture_output=True)

            (repo / "sample.py").write_text(
                'import argparse\n'
                'parser = argparse.ArgumentParser()\n'
                'parser.add_argument("--new-name")\n',
                encoding="utf-8"
            )

            findings = detect_documentation_drift(repo)

            self.assertTrue(
                any(
                    finding["status"] == "likely_drift"
                    and finding["old_value"] == "--old-name"
                    and finding["new_value"] == "--new-name"
                    for finding in findings
                )
            )


if __name__ == "__main__":
    unittest.main()
