import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docuguard.rag import (
    RAGError,
    load_snapshot,
    query_snapshot,
    resolve_snapshot,
)


class SnapshotRAGTests(unittest.TestCase):
    def _make_snapshot(self, root: Path) -> Path:
        snapshot = root / "demo-project" / "snapshot-001"
        snapshot.mkdir(parents=True)
        manifest = {
            "schema_version": "1.0",
            "project": {"project_id": "demo-project", "project_name": "Demo Project"},
            "snapshot": {"snapshot_id": "snapshot-001", "generated_at": "2026-11-19T10:00:00+00:00"},
            "counts": {"indexed_files": 2, "chunks": 2, "summaries": 1},
        }
        (snapshot / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        chunks = [
            {
                "chunk_id": "chunk-doc-1",
                "project_id": "demo-project",
                "source_id": "docs",
                "source_type": "documentation",
                "kind": "documentation_paragraph",
                "path": "docs/configuration.md",
                "start_line": 8,
                "end_line": 8,
                "content": "The application loads the CA certificate from SSL_CERT_FILE.",
                "content_hash": "hash1",
            },
            {
                "chunk_id": "chunk-code-1",
                "project_id": "demo-project",
                "source_id": "code",
                "source_type": "code",
                "kind": "python_assignment",
                "path": "src/client.py",
                "start_line": 14,
                "end_line": 14,
                "content": "SSL_CERT_FILE = os.environ.get('SSL_CERT_FILE')",
                "content_hash": "hash2",
            },
        ]
        (snapshot / "chunks.jsonl").write_text(
            "".join(json.dumps(item) + "\n" for item in chunks), encoding="utf-8"
        )
        summary = {
            "summary_id": "summary-doc-1",
            "project_id": "demo-project",
            "source_id": "docs",
            "path": "docs/configuration.md",
            "summary_method": "extractive_v1",
            "summary_text": "SSL_CERT_FILE environment variable and CA certificate configuration.",
            "source_chunk_ids": ["chunk-doc-1"],
            "chunk_count": 1,
            "summary_scope": "section",
            "section": "TLS configuration",
        }
        (snapshot / "summaries.jsonl").write_text(
            json.dumps(summary) + "\n", encoding="utf-8"
        )
        return snapshot

    def test_resolves_newest_snapshot_and_loads_organised_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot = self._make_snapshot(root)
            self.assertEqual(resolve_snapshot(root), snapshot)
            loaded = load_snapshot(root)
            self.assertEqual(len(loaded["chunks"]), 2)
            self.assertEqual(len(loaded["summaries"]), 1)

    def test_retrieval_uses_chunks_and_summary_navigation(self):
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = self._make_snapshot(Path(temporary))
            with patch("docuguard.rag.get_api_key", return_value=None):
                result = query_snapshot(
                    snapshot,
                    "Where is SSL_CERT_FILE used to load CA certificates?",
                    llm_mode="off",
                )
            self.assertEqual(result["generation_status"], "retrieval_only")
            self.assertTrue(result["citations"])
            self.assertEqual(result["citations"][0]["path"], "docs/configuration.md")
            self.assertEqual(result["citations"][0]["start_line"], 8)
            self.assertTrue(result["retrieved_summaries"])

    def test_llm_answer_citations_are_validated_against_retrieved_chunks(self):
        with tempfile.TemporaryDirectory() as temporary:
            snapshot = self._make_snapshot(Path(temporary))
            with (
                patch("docuguard.rag.get_api_key", return_value="configured"),
                patch("docuguard.rag.get_model", return_value="test-model"),
                patch(
                    "docuguard.rag.create_structured_response",
                    return_value={
                        "answer": "The docs state that SSL_CERT_FILE supplies the CA certificate path.",
                        "citations": ["chunk-doc-1", "not-a-real-chunk"],
                    },
                ),
            ):
                result = query_snapshot(
                    snapshot,
                    "What does SSL_CERT_FILE do?",
                    llm_mode="required",
                )
            self.assertEqual(result["generation_status"], "llm_rag")
            self.assertEqual([item["chunk_id"] for item in result["citations"]], ["chunk-doc-1"])

    def test_missing_snapshot_raises_helpful_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(RAGError):
                load_snapshot(Path(temporary) / "empty-index")


if __name__ == "__main__":
    unittest.main()
