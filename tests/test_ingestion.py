from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from docuguard.ingestion.extractors import extract_documentation, extract_source
from docuguard.ingestion.organizer import ingest_project
from docuguard.ingestion.sources import SourceError, validate_github_url
from docuguard.ingestion.zip_utils import UnsafeArchiveError, safe_extract_zip
from docuguard.ingestion import website
from unittest.mock import patch


class DocumentationExtractionTests(unittest.TestCase):
    def test_markdown_extracts_heading_paragraph_table_and_fenced_example(self):
        text = "\n".join([
            "# Configuration",
            "",
            "The application listens on port 9000.",
            "",
            "| Option | Default |",
            "| --- | --- |",
            "| timeout | 30 |",
            "",
            "```python",
            "PORT = 9000",
            "```",
        ])
        chunks = extract_documentation(text, ".md")
        kinds = [chunk["kind"] for chunk in chunks]
        self.assertIn("documentation_heading", kinds)
        self.assertIn("documentation_paragraph", kinds)
        self.assertIn("documentation_table_row", kinds)
        html_row = next(chunk for chunk in chunks if chunk["kind"] == "documentation_table_row")
        self.assertIn("Option", html_row["content"])
        self.assertIn("Default", html_row["content"])
        self.assertIn("code_example", kinds)
        paragraph = next(chunk for chunk in chunks if chunk["kind"] == "documentation_paragraph")
        self.assertEqual(paragraph["start_line"], 3)
        self.assertEqual(paragraph["section"], "Configuration")
        example = next(chunk for chunk in chunks if chunk["kind"] == "code_example")
        self.assertEqual(example["language"], "python")
        self.assertEqual(example["content"], "PORT = 9000")
        self.assertEqual(example["start_line"], 10)

    def test_rst_code_block_is_extracted(self):
        text = "Example\n=======\n\n.. code-block:: python\n\n   DEFAULT_PORT = 8000\n"
        chunks = extract_documentation(text, ".rst")
        examples = [chunk for chunk in chunks if chunk["kind"] == "code_example"]
        self.assertEqual(len(examples), 1)
        self.assertEqual(examples[0]["language"], "python")
        self.assertIn("DEFAULT_PORT = 8000", examples[0]["content"])

    def test_html_extracts_paragraph_heading_table_and_code(self):
        text = "<h1>Install</h1>\n<p>Use the CLI.</p>\n<table><tr><th>Option</th><th>Default</th></tr><tr><td>port</td><td>9000</td></tr></table>\n<pre><code class='language-python'>run()</code></pre>"
        chunks = extract_documentation(text, ".html")
        kinds = [chunk["kind"] for chunk in chunks]
        self.assertIn("documentation_heading", kinds)
        self.assertIn("documentation_paragraph", kinds)
        self.assertIn("code_example", kinds)
        self.assertIn("documentation_table_row", kinds)
        html_row = next(chunk for chunk in chunks if chunk["kind"] == "documentation_table_row")
        self.assertIn("Option", html_row["content"])
        self.assertIn("Default", html_row["content"])


class SourceExtractionTests(unittest.TestCase):
    def test_python_extracts_functions_classes_docstrings_comments_and_assignments(self):
        source = '''"""Module-level overview."""\n# module comment\nDEFAULT_PORT = 9000\n\nclass Server:\n    """Server object documentation."""\n    # class comment\n    PORT = 9000\n    def start(self):\n        """Start the server."""\n        # start comment\n        return DEFAULT_PORT\n'''
        chunks = extract_source(source, "python", ".py")
        kinds = [chunk["kind"] for chunk in chunks]
        self.assertIn("python_docstring", kinds)
        self.assertIn("python_comment", kinds)
        self.assertIn("python_assignment", kinds)
        self.assertIn("python_class", kinds)
        self.assertIn("python_function", kinds)
        symbols = {chunk["symbol"] for chunk in chunks if chunk["kind"] == "python_function"}
        self.assertIn("Server.start", symbols)
        assignment = next(chunk for chunk in chunks if chunk["kind"] == "python_assignment")
        self.assertEqual(assignment["symbol"], "DEFAULT_PORT")
        method_doc = next(
            chunk for chunk in chunks
            if chunk["kind"] == "python_docstring" and chunk["symbol"] == "Server.start"
        )
        self.assertEqual(method_doc["content"], "Start the server.")
        self.assertEqual(method_doc["start_line"], 10)
        class_assignment = next(
            chunk for chunk in chunks
            if chunk["kind"] == "python_assignment" and chunk.get("symbol") == "PORT"
        )
        self.assertEqual(class_assignment["parent_symbol"], "Server")

    def test_generic_language_extracts_source_blocks_and_comments(self):
        source = "// public API\nfunction run() {\n  return 1;\n}\n"
        chunks = extract_source(source, "javascript", ".js")
        self.assertTrue(any(chunk["kind"] == "source_block" for chunk in chunks))
        self.assertTrue(any(chunk["kind"] == "source_comment" for chunk in chunks))


class IngestionOrganisationTests(unittest.TestCase):
    def _make_project(self, root: Path):
        (root / "src").mkdir()
        (root / "docs").mkdir()
        (root / "src" / "server.py").write_text(
            '"""Server module."""\n# Default listening port\nDEFAULT_PORT = 9000\n\ndef start():\n    """Start the service."""\n    return DEFAULT_PORT\n',
            encoding="utf-8",
        )
        (root / "docs" / "configuration.md").write_text(
            "# Server configuration\n\nThe server listens on port 9000.\n\n```python\nDEFAULT_PORT = 9000\n```\n",
            encoding="utf-8",
        )
        (root / ".env").write_text("API_KEY=should-not-be-ingested\n", encoding="utf-8")
        (root / "node_modules").mkdir()
        (root / "node_modules" / "dependency.js").write_text("// ignored\n", encoding="utf-8")

    def test_ingest_writes_versioned_snapshot_with_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            root.mkdir()
            self._make_project(root)
            output = Path(temporary) / "index"
            result = ingest_project(repo_path=root, project_name="Demo Project", output_dir=output)

            snapshot = Path(result.output_dir)
            self.assertTrue((snapshot / "manifest.json").is_file())
            self.assertTrue((snapshot / "files.jsonl").is_file())
            self.assertTrue((snapshot / "chunks.jsonl").is_file())
            self.assertTrue((snapshot / "summaries.jsonl").is_file())
            self.assertTrue((snapshot / "project_summary.json").is_file())

            manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], "1.0")
            self.assertFalse(manifest["future_rag"]["embeddings_created"])
            self.assertTrue(manifest["future_rag"]["raw_chunks_preserved"])

            chunks = [json.loads(line) for line in (snapshot / "chunks.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertTrue(chunks)
            self.assertTrue(all(chunk["chunk_id"] and chunk["content_hash"] for chunk in chunks))
            self.assertTrue(all(chunk["start_line"] >= 1 and chunk["end_line"] >= chunk["start_line"] for chunk in chunks))
            self.assertTrue(any(chunk["kind"] == "python_function" for chunk in chunks))
            self.assertTrue(any(chunk["kind"] == "python_comment" for chunk in chunks))
            self.assertTrue(any(chunk["kind"] == "code_example" for chunk in chunks))
            self.assertFalse(any("should-not-be-ingested" in chunk["content"] for chunk in chunks))
            self.assertFalse(any("node_modules" in chunk["path"] for chunk in chunks))
            summaries = [json.loads(line) for line in (snapshot / "summaries.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertTrue(summaries)
            self.assertTrue(all(summary["summary_method"] == "extractive_v1" for summary in summaries))
            self.assertTrue(all(summary["source_chunk_ids"] for summary in summaries))
            self.assertTrue(any(summary["summary_scope"] == "section" for summary in summaries))

    def test_probable_literal_credentials_are_skipped(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            (root / "settings.yaml").write_text(
                "api_key: " + ("a" * 36) + "\n", encoding="utf-8"
            )
            result = ingest_project(repo_path=root, output_dir=Path(temporary) / "index")
            files = [json.loads(line) for line in (Path(result.output_dir) / "files.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0]["status"], "skipped")
            self.assertIn("credential", files[0]["warning"])
            self.assertEqual(result.chunk_count, 0)

    def test_separate_documentation_root_is_supported(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            code = base / "code"
            docs = base / "docs"
            code.mkdir()
            docs.mkdir()
            (code / "server.py").write_text("DEFAULT_PORT = 9000\n", encoding="utf-8")
            (docs / "guide.md").write_text("# Guide\n\nPort is 9000.\n", encoding="utf-8")
            result = ingest_project(repo_path=code, docs_path=docs, output_dir=base / "index")
            chunks = [json.loads(line) for line in Path(result.chunks_path).read_text(encoding="utf-8").splitlines()]
            self.assertTrue(any(chunk["source_id"] == "code" and chunk["kind"] == "python_assignment" for chunk in chunks))
            self.assertTrue(any(chunk["source_id"] == "docs" and chunk["kind"] == "documentation_paragraph" for chunk in chunks))

    def test_output_inside_source_root_must_use_reserved_docuguard_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            (root / "readme.md").write_text("Docs.\n", encoding="utf-8")
            with self.assertRaisesRegex(Exception, "Output directory must be outside source roots"):
                ingest_project(repo_path=root, output_dir=root / "generated-index")


class SourceSafetyTests(unittest.TestCase):
    def test_github_url_validation(self):
        self.assertEqual(
            validate_github_url("https://github.com/owner/project"),
            "https://github.com/owner/project.git",
        )
        with self.assertRaises(SourceError):
            validate_github_url("https://github.com.evil.example/owner/project")
        with self.assertRaises(SourceError):
            validate_github_url("https://user:secret@github.com/owner/project")
        with self.assertRaises(SourceError):
            validate_github_url("https://github.com/owner/project/tree/main")

    def test_safe_zip_extracts_normal_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            archive = base / "source.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("project/README.md", "Hello\n")
            destination = safe_extract_zip(archive, base / "unpacked")
            self.assertEqual((destination / "project" / "README.md").read_text(encoding="utf-8"), "Hello\n")

    def test_website_crawler_stays_on_same_origin_and_saves_html(self):
        pages = {
            "https://docs.example.com/": '<h1>Home</h1><a href="/guide">Guide</a><a href="https://outside.example/page">External</a>',
            "https://docs.example.com/guide": '<h1>Guide</h1><p>Install the package.</p>',
        }
        def fake_fetch(url, *, timeout, max_bytes):
            return pages[url], url
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(website, "_assert_public_host"), patch.object(website, "_fetch_html", side_effect=fake_fetch):
                count = website.crawl_documentation_website(
                    "https://docs.example.com/", Path(temporary), max_pages=10,
                    max_depth=2, delay_seconds=0,
                )
            self.assertEqual(count, 2)
            self.assertTrue((Path(temporary) / "index.html").is_file())
            self.assertTrue((Path(temporary) / "guide.html").is_file())
            self.assertFalse((Path(temporary) / "page.html").exists())

    def test_website_rejects_private_ip_resolution(self):
        with patch.object(website.socket, "getaddrinfo", return_value=[(None, None, None, None, ("127.0.0.1", 0))]):
            with self.assertRaisesRegex(SourceError, "non-public IP"):
                website._assert_public_host("localhost")

    def test_safe_zip_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            archive = base / "bad.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("../escape.txt", "bad")
            with self.assertRaises(UnsafeArchiveError):
                safe_extract_zip(archive, base / "unpacked")


if __name__ == "__main__":
    unittest.main()
