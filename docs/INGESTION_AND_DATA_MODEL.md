# DocuGuard ingestion and data organisation prototype

This stage collects source material and stores it in a versioned, provenance-preserving format. It intentionally does **not** create embeddings, call an LLM, or make semantic drift decisions. The output is designed to become the input to the later RAG layer.

## Inputs

The CLI accepts a checked-out directory, a GitHub repository URL, or a ZIP archive as the source-code input. A separate documentation source can be supplied in the same three forms. If no separate documentation input is supplied, DocuGuard looks for documentation in the code repository.

```bash
# Local repository, docs in the same repository
python -m docuguard.ingestion --repo ../my-project --project-name MyProject

# Separate docs checkout
python -m docuguard.ingestion --repo ../my-project --docs-path ../my-project-docs

# Public GitHub repositories
python -m docuguard.ingestion --repo-url https://github.com/owner/project --branch main
python -m docuguard.ingestion --repo-url https://github.com/owner/source --docs-url https://github.com/owner/docs

# ZIP upload inputs (useful for a future webpage upload form)
python -m docuguard.ingestion --repo-zip ./source.zip --docs-zip ./documentation.zip

# Public static HTML documentation site (same-origin, bounded crawl)
python -m docuguard.ingestion --repo ../my-project --docs-website https://docs.example.com/

# Machine-readable output for a future web backend
python -m docuguard.ingestion --repo ../my-project --json
```

Private GitHub clones can use `DOCUGUARD_GITHUB_TOKEN` as an environment variable. The token is not embedded in the clone URL, written into the project snapshot, or printed by DocuGuard. Give it read-only repository access. Never put it in frontend JavaScript or commit it to Git.

## Extracted content

- Documentation: Markdown, reStructuredText, plain text, AsciiDoc and HTML.
- Documentation structure: headings/sections, paragraphs, list items and Markdown table rows.
- Documentation examples: Markdown fenced code blocks, reStructuredText `code-block` directives and HTML `pre`/`code` blocks.
- Public documentation websites: bounded same-origin static HTML crawl (100 pages and depth 3 by default); JavaScript-rendered pages and authenticated websites are not supported. Only crawl sites you are authorised to access; check the site's terms and robots policy before crawling.
- Python: modules' docstrings, functions, classes, assignments, comments and source locations.
- Other common source languages: bounded source blocks and best-effort line/block comments. These are heuristic extractors, not full language parsers; Python uses the standard-library AST/tokenizer.
- Configuration: JSON, YAML, TOML, INI, properties and XML as bounded blocks.

The crawler excludes common dependency/build/cache directories, symlinks, known secret filenames and key/certificate extensions. It also skips files containing several common literal credential patterns. It only reads UTF-8 text (Python source also honours PEP 263 encoding declarations). The defaults cap individual files at 2 MiB, total ingested source bytes at 200 MiB, and discovered files at 20,000. Website fetching is restricted to public IP addresses and the submitted site's original origin, and each page is capped at 2 MiB. These limits are configurable through the Python service function; the CLI currently uses safe defaults.

## Stored snapshot

By default, output is written beneath `.docuguard/index/` (which is excluded from future crawls):

```text
.docuguard/index/<project_id>/<snapshot_id>/
  manifest.json
  files.jsonl
  chunks.jsonl
  summaries.jsonl
  project_summary.json
```

Every chunk has a stable `chunk_id`, `project_id`, `source_id`, source kind, file path, line range, exact text, content hash, language/symbol metadata, and source commit SHA when available. JSONL keeps the corpus streamable and convenient for vector-store ingestion. `files.jsonl` records the indexed file catalogue and warnings/skips. `summaries.jsonl` contains **extractive** per-file and per-section summaries linked to their source chunk IDs. `project_summary.json` contains corpus counts and metadata. No original chunk is discarded after summary generation.

A snapshot is separated by repository commit(s) and content fingerprint. This is versioned storage, not incremental indexing: unchanged files are still rescanned for each ingestion run in this prototype.

## Webpage/backend contract

A future webpage should upload ZIP bytes or submit validated GitHub URLs to a backend. The backend should stage files in a private temporary directory, enforce upload quotas, and call the library function `docuguard.ingestion.ingest_project(...)` or the JSON-compatible helper `ingest_local_project(request)`. For a website source, the backend can invoke the bounded crawler before calling the ingestion function.

Example internal service request after the backend stages the uploaded files:

```json
{
  "project_name": "MyProject",
  "code_root": "/private/staging/project-source",
  "docs_root": "/private/staging/project-docs",
  "output_dir": "/private/data/docuguard/index",
  "code_origin": "https://github.com/owner/source",
  "docs_origin": "https://github.com/owner/docs"
}
```

Do not expose `code_root` or `docs_root` as arbitrary filesystem path inputs to a public browser client. They are trusted backend-only fields. A later FastAPI adapter should accept multipart uploads / validated repository URLs, stage them safely, then invoke the service function.

## Snapshot-backed RAG integration

The snapshot schema now feeds a local RAG query layer:

~~~powershell
python -m docuguard.rag --index .docuguard/index --query "Where is this configuration option used?"
~~~

The RAG layer loads the manifest, raw chunks and extractive summaries from the selected snapshot. BM25 retrieval ranks raw evidence chunks; summary-to-chunk links help navigate to relevant passages. When configured, hybrid retrieval combines BM25 and cached provider embeddings. The LLM receives the question, retrieved raw evidence and navigation summaries, then returns an answer with chunk IDs. DocuGuard validates every returned citation against the retrieved chunk IDs and renders the original source path and line range.

Use --llm-mode off for retrieval-only output without API calls. Use --llm-mode required when the user needs to prove that generation ran; auto mode attempts generation when a key is configured and labels retrieval-only fallback when the service is unavailable.

The RAG CLI and complete example are documented in docs/RAG_QUICKSTART.md. Snapshot summaries remain extractive and preserve links to the original chunks; they are not presented as LLM-generated summaries.
