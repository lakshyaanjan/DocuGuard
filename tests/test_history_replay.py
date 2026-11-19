import subprocess
import tempfile
import unittest
from pathlib import Path

from docuguard.history_replay import (
    find_replay_candidates,
    replay_candidate,
    has_source_changes,
    is_documentation_only,
    changed_text_tokens,
    score_change_relevance,
    classify_llm_runtime,
)


class HistoryReplayTests(unittest.TestCase):

    def test_llm_runtime_status_distinguishes_provider_fallback(self):
        self.assertEqual(
            classify_llm_runtime("auto", True, True),
            "deterministic_fallback_after_llm_error",
        )
        self.assertEqual(
            classify_llm_runtime("auto", True, False),
            "llm_configured_no_fallback_warning",
        )
        self.assertEqual(
            classify_llm_runtime("auto", False, False),
            "deterministic_only_no_api_key",
        )
        self.assertEqual(
            classify_llm_runtime("off", True, False),
            "deterministic_only",
        )

    def test_documentation_only_classifier(self):
        self.assertTrue(is_documentation_only(["README.md", "docs/setup.rst"]))
        self.assertFalse(is_documentation_only(["README.md", "app.py"]))
        self.assertFalse(is_documentation_only([]))

    def test_source_change_classifier(self):
        self.assertTrue(has_source_changes(["src/app.py"]))
        self.assertTrue(has_source_changes(["src/main.rs"]))
        self.assertFalse(has_source_changes(["README.md", "docs/guide.html"]))

    def test_pairs_code_change_with_following_docs_only_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)

            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Replay Tests"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "replay@docuguard.local"], cwd=repo, check=True)

            (repo / "app.py").write_text("DEFAULT_TIMEOUT = 30\n", encoding="utf-8")
            (repo / "README.md").write_text("The default timeout is 30 seconds.\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "Initial version"], cwd=repo, check=True, capture_output=True)

            (repo / "app.py").write_text("DEFAULT_TIMEOUT = 60\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "Change default timeout"], cwd=repo, check=True, capture_output=True)
            code_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                capture_output=True, text=True
            ).stdout.strip()

            (repo / "README.md").write_text("The default timeout is 60 seconds.\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "docs: update timeout default"], cwd=repo, check=True, capture_output=True)
            docs_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                capture_output=True, text=True
            ).stdout.strip()

            pairs = find_replay_candidates(repo, window_days=30, max_pairs=5)
            self.assertEqual(len(pairs), 1)
            self.assertEqual(pairs[0]["code_commit"], code_sha)
            self.assertEqual(pairs[0]["docs_commit"], docs_sha)
            self.assertEqual(pairs[0]["docs_files"], ["README.md"])
            self.assertGreaterEqual(pairs[0]["relevance_score"], 2)
            self.assertIn("timeout", pairs[0]["shared_terms"])


    def test_changed_text_overlap_scores_exact_identifiers_higher(self):
        code = changed_text_tokens("+SSL_CERT_FILE = configured\n")
        docs = changed_text_tokens("-SSL_CERT_FILE was ignored\n+HTTPX respects SSL_CERT_FILE\n")
        score, shared = score_change_relevance(code, docs)
        self.assertGreaterEqual(score, 3)
        self.assertIn("ssl_cert_file", shared)

    def test_unrelated_docs_only_commit_is_not_a_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Replay Tests"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "replay@docuguard.local"], cwd=repo, check=True)
            (repo / "app.py").write_text("DEFAULT_TIMEOUT = 30\n", encoding="utf-8")
            (repo / "README.md").write_text("Contributor guide.\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=repo, check=True, capture_output=True)
            (repo / "app.py").write_text("DEFAULT_TIMEOUT = 60\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "Change timeout"], cwd=repo, check=True, capture_output=True)
            (repo / "README.md").write_text("Contribution guidelines now mention code review.\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "docs: clarify contribution workflow"], cwd=repo, check=True, capture_output=True)

            pairs = find_replay_candidates(repo, window_days=30, max_pairs=5)
            self.assertEqual(pairs, [])

    def test_selects_related_commit_instead_of_nearest_unrelated_source_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Replay Tests"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "replay@docuguard.local"], cwd=repo, check=True)
            (repo / "app.py").write_text("SSL_CERT_FILE_ENABLED = False\n", encoding="utf-8")
            (repo / "README.md").write_text("SSL_CERT_FILE is not respected by default.\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "Initial"], cwd=repo, check=True, capture_output=True)

            (repo / "app.py").write_text("SSL_CERT_FILE_ENABLED = True\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "Respect SSL_CERT_FILE"], cwd=repo, check=True, capture_output=True)
            relevant_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()

            (repo / "utility.py").write_text("def clear_cache():\n    return True\n", encoding="utf-8")
            subprocess.run(["git", "add", "utility.py"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "Add cache helper"], cwd=repo, check=True, capture_output=True)

            (repo / "README.md").write_text("HTTPX now respects SSL_CERT_FILE by default.\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "docs: correct SSL_CERT_FILE behavior"], cwd=repo, check=True, capture_output=True)

            pairs = find_replay_candidates(repo, window_days=30, max_pairs=5)
            self.assertEqual(len(pairs), 1)
            self.assertEqual(pairs[0]["code_commit"], relevant_sha)
            self.assertIn("ssl", pairs[0]["shared_terms"])

    def test_replay_runs_docuguard_on_original_code_change_state(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)

            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Replay Tests"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "replay@docuguard.local"], cwd=repo, check=True)

            (repo / "sample.py").write_text(
                "APPLICATION_DEFAULT_PORT = 8000\n", encoding="utf-8"
            )
            (repo / "README.md").write_text(
                "The application runs on port 8000 by default.\n",
                encoding="utf-8"
            )
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-m", "Initial version"],
                cwd=repo, check=True, capture_output=True
            )

            (repo / "sample.py").write_text(
                "APPLICATION_DEFAULT_PORT = 9000\n", encoding="utf-8"
            )
            subprocess.run(["git", "add", "sample.py"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-m", "Change application port"],
                cwd=repo, check=True, capture_output=True
            )
            code_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                capture_output=True, text=True
            ).stdout.strip()
            parent_sha = subprocess.run(
                ["git", "rev-parse", "HEAD^"], cwd=repo, check=True,
                capture_output=True, text=True
            ).stdout.strip()

            (repo / "README.md").write_text(
                "The application runs on port 9000 by default.\n",
                encoding="utf-8"
            )
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
            subprocess.run(
                ["git", "commit", "-m", "docs: update default port"],
                cwd=repo, check=True, capture_output=True
            )
            docs_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                capture_output=True, text=True
            ).stdout.strip()

            candidate = {
                "code_commit": code_sha,
                "code_parent": parent_sha,
                "code_files": ["sample.py"],
                "docs_commit": docs_sha,
                "docs_files": ["README.md"],
                "gap_seconds": 1
            }
            result = replay_candidate(repo, candidate)

            self.assertEqual(result["outcome"], "caught")
            self.assertEqual(result["matched_finding_count"], 1)
            self.assertEqual(
                result["matched_findings"][0]["documentation"]["file"],
                "README.md"
            )


if __name__ == "__main__":
    unittest.main()
