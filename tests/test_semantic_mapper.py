import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docuguard.semantic_mapper import (
    _build_code_changes,
    _make_finding,
    detect_semantic_drift,
    rank_documents_lexically,
)


class SemanticRetrievalTests(unittest.TestCase):
    def test_lexical_retrieval_prefers_relevant_documentation(self):
        documents = [
            {"content": "The HTTP application listens on port 8080 by default."},
            {"content": "The payment processor signs outbound messages with HMAC."},
            {"content": "The database connection retries after a timeout."},
        ]
        ranked = rank_documents_lexically(
            "APPLICATION_DEFAULT_PORT changed from 8080 to 9090",
            documents,
            limit=1,
        )
        self.assertEqual(ranked[0][0], 0)
        self.assertGreater(ranked[0][1], 0)

    def _make_repo(self, root):
        subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "DocuGuard Tests"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "tests@docuguard.local"], cwd=root, check=True)
        (root / "server.py").write_text(
            "APPLICATION_DEFAULT_PORT = 8080\n",
            encoding="utf-8",
        )
        (root / "README.md").write_text(
            "# Operations\n\n"
            "The HTTP application listens on port 8080 by default.\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=root, check=True, capture_output=True)

    def test_changed_source_context_has_exact_git_line_references(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self._make_repo(repo)
            (repo / "server.py").write_text(
                "APPLICATION_DEFAULT_PORT = 9090\n",
                encoding="utf-8",
            )
            changes = _build_code_changes(repo)
            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0]["file"], "server.py")
            self.assertEqual(changes[0]["old_line"], 1)
            self.assertEqual(changes[0]["new_line"], 1)
            self.assertIn("8080", changes[0]["query_text"])
            self.assertIn("9090", changes[0]["query_text"])

    def test_semantic_pipeline_uses_local_citations_not_model_supplied_lines(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            self._make_repo(repo)
            (repo / "server.py").write_text(
                "APPLICATION_DEFAULT_PORT = 9090\n",
                encoding="utf-8",
            )

            with patch(
                "docuguard.semantic_mapper.create_structured_response",
                return_value={
                    "analyses": [{
                        "doc_index": 0,
                        "classification": "likely_drift",
                        "confidence": 0.94,
                        "explanation": "The documented default contradicts the current code.",
                        "suggested_text": "The HTTP application listens on port 9090 by default.",
                    }]
                },
            ):
                findings = detect_semantic_drift(repo, use_embeddings=False)

            self.assertEqual(len(findings), 1)
            finding = findings[0]
            self.assertEqual(finding["status"], "likely_drift")
            self.assertEqual(finding["analysis_source"], "llm_semantic")
            self.assertEqual(finding["documentation"]["file"], "README.md")
            self.assertEqual(finding["documentation"]["line"], 3)
            self.assertEqual(finding["code_change"]["file"], "server.py")
            self.assertEqual(finding["code_change"]["new_line"], 1)
            self.assertEqual(
                finding["suggested_sentence"],
                "The HTTP application listens on port 9090 by default.",
            )

    def test_historical_or_low_confidence_model_results_need_review(self):
        change = {
            "file": "server.py",
            "old_line": 2,
            "new_line": 2,
            "removed_lines": [{"line": 2, "content": "old"}],
            "added_lines": [{"line": 2, "content": "new"}],
            "identifiers": ["SERVER_DEFAULT_PORT"],
        }
        document = {
            "file": "README.md",
            "line": 4,
            "type": "sentence",
            "content": "Previously the application listened on port 8080.",
        }
        result = {
            "classification": "likely_drift",
            "confidence": 0.98,
            "explanation": "The passage is historical.",
            "suggested_text": "The application listens on port 9090.",
        }
        finding = _make_finding(change, document, result, 0.8, "test-model")
        self.assertEqual(finding["status"], "needs_review")
        self.assertIsNone(finding["suggested_sentence"])

        result["confidence"] = 0.7
        document["content"] = "The application listens on port 8080."
        finding = _make_finding(change, document, result, 0.8, "test-model")
        self.assertEqual(finding["status"], "needs_review")


if __name__ == "__main__":
    unittest.main()
