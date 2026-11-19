# DocuGuard

**Catch documentation that a code change made wrong.**

DocuGuard is a pull-request documentation drift checker. It examines code changes, retrieves the documentation passages most likely to describe those changes, and reports whether the passages have become stale. Each finding points back to the exact documentation file/line and the changed code file/line.

## What it does

- Detects removed or renamed literal argparse command-line flags.
- Detects changed simple Python scalar defaults and selected configuration dictionary changes.
- Uses lexical retrieval and (when configured) semantic embeddings to connect changed source files to documentation sentences and Markdown table rows.
- Uses an LLM through an OpenAI-compatible Chat Completions API to judge whether a retrieved passage is actually inaccurate, rather than treating every keyword match as drift.
- Supports OpenAI-compatible providers, including Google AI Studio's Gemini API.
- Labels uncertain and historical passages for human review.
- Produces HTML and JSON reports, GitHub Actions annotations, and a Markdown job summary.
- Proposes corrections when evidence supports one. It never modifies, commits, or pushes documentation automatically.
- Ingests local projects, GitHub repositories, ZIP archives, separate docs checkouts, and bounded public static HTML docs sites into provenance-preserving snapshots.

The semantic mapper supports common source extensions, but language understanding is model-assisted and best-effort. Deterministic checks remain deliberately narrow and explainable.

## Quick start

Requirements: Python 3.10+ and Git. The LLM layer is optional.

~~~powershell
git clone https://github.com/lakshyaanjan/DocuGuard.git
cd DocuGuard
python -m unittest discover -s tests -v
python app.py --llm-mode off --html-out docuguard-report.html --json-out docuguard-report.json
~~~

Open the generated HTML file in a browser.

## Run the end-to-end demo

~~~powershell
python examples/run_demo.py
~~~

This creates a temporary Git project, changes the code's default port from 8000 to 9090, leaves the README stale, and runs DocuGuard. It produces a self-contained HTML report and a JSON report under demo-output/.

For an offline deterministic demo:

~~~powershell
python examples/run_demo.py --llm-mode off
~~~

## Enable semantic LLM review

DocuGuard uses the OpenAI-compatible Chat Completions and Embeddings endpoints. The API key and model are selected through environment variables. Do not commit API keys.

### Google AI Studio (Gemini free tier)

Create a Gemini API key in https://aistudio.google.com/apikey, then configure the current PowerShell session:

~~~powershell
$secureKey = Read-Host "Paste your Gemini API key" -AsSecureString
$env:GEMINI_API_KEY = ([System.Net.NetworkCredential]::new("", $secureKey)).Password
Remove-Variable secureKey

$env:DOCUGUARD_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
$env:DOCUGUARD_LLM_MODEL = "gemini-3.6-flash"
$env:DOCUGUARD_EMBEDDING_MODEL = "gemini-embedding-2-preview"
$env:DOCUGUARD_USE_EMBEDDINGS = "false"

python examples/run_demo.py --llm-mode required --no-embeddings
~~~

This runs the Gemini judge with lexical retrieval, so it does not call the embeddings endpoint. Google lists Gemini 3.6 Flash as available on the free tier; free-tier availability and rate limits depend on the Google AI Studio project. Free-tier content may be used to improve Google's products, so do not send private or sensitive source code unless that use is acceptable.

To enable Gemini embeddings as well, set DOCUGUARD_USE_EMBEDDINGS to true and retain gemini-embedding-2-preview as the embedding model. Embedding availability and quotas are subject to the active AI Studio project limits.

### Other OpenAI-compatible providers

For an OpenAI API key, set OPENAI_API_KEY and use the default API base/model, or configure DOCUGUARD_OPENAI_BASE_URL and DOCUGUARD_LLM_MODEL for another provider that supports Chat Completions structured outputs and embeddings.

For GitHub Actions, add the relevant provider key as a repository secret. For Gemini, add GEMINI_API_KEY, then add repository variables DOCUGUARD_OPENAI_BASE_URL and DOCUGUARD_LLM_MODEL with the Gemini values above. The PR workflow remains deterministic when no supported API key is present.

Analysis modes:

| Mode | Behavior |
|---|---|
| auto | Uses the configured LLM when a key is present; retains deterministic results with a warning on model/API failure |
| off | Runs deterministic checks only; no API requests |
| required | Requires the model API and fails clearly if it is unavailable |

Use --no-embeddings to keep the LLM judge but retrieve candidates lexically.

Configuration:

| Environment variable | Default | Purpose |
|---|---|---|
| OPENAI_API_KEY | unset | OpenAI API credential |
| GEMINI_API_KEY | unset | Google AI Studio Gemini API credential |
| GOOGLE_API_KEY | unset | Alternative Google API credential name |
| DOCUGUARD_OPENAI_API_KEY | unset | Alternative API key name |
| DOCUGUARD_OPENAI_BASE_URL | https://api.openai.com/v1 | OpenAI-compatible API base URL |
| DOCUGUARD_LLM_MODEL | gpt-6.2-astra | Chat Completions model |
| DOCUGUARD_EMBEDDING_MODEL | text-embedding-3-small | Embeddings model |
| DOCUGUARD_USE_EMBEDDINGS | true | Enable semantic-vector retrieval |
| DOCUGUARD_CACHE_DIR | ~/.cache/docuguard | Local embedding cache |
| DOCUGUARD_LLM_MODE | auto | Default analysis mode |

The client uses Python's standard library and adds no package dependency. It calls the Chat Completions endpoint with JSON Schema structured output and the embeddings endpoint for vector representations. Use a model available to your API account; change DOCUGUARD_LLM_MODEL and DOCUGUARD_EMBEDDING_MODEL when needed.

The semantic stage uses bounded retrieval: by default, up to eight changed source files and eight candidate documentation passages per file are sent to the model. Documentation embeddings are cached locally outside the repository by model and content hash. Exact citation paths and line numbers come from DocuGuard's extractors, not model output.

## Analyse separate documentation sources

~~~powershell
python app.py --repo ..\source --docs-path ..\documentation
python app.py --repo ..\source --docs-url https://github.com/owner/docs --docs-branch main
python app.py --repo ..\source --docs-zip .\docs.zip
python app.py --repo ..\source --docs-website https://docs.example.com/
~~~

GitHub docs repositories can be private when DOCUGUARD_GITHUB_TOKEN is configured with read-only access. Website crawling is restricted to bounded public static HTML on the submitted same origin. It rejects private-address resolutions and cross-origin redirects; JavaScript-rendered/authenticated sites are not supported.

## Repository ingestion and snapshots

DocuGuard includes a standalone ingestion/data-organisation layer for downstream analysis:

~~~powershell
python -m docuguard.ingestion --repo ..\your-project --project-name Demo
python -m docuguard.ingestion --repo ..\your-project --docs-path ..\your-docs
python -m docuguard.ingestion --repo-url https://github.com/owner/project --branch main
python -m docuguard.ingestion --repo-zip .\source.zip --docs-zip .\docs.zip
python -m docuguard.ingestion --repo ..\your-project --docs-website https://docs.example.com/
~~~

Versioned snapshots are stored below .docuguard/index/ and preserve chunks, content hashes, source commit metadata, file paths, symbols, sections, and line ranges. See docs/INGESTION_AND_DATA_MODEL.md for the schema and safety limits.

## Historical replay

The GitHub Actions workflow **DocuGuard Historical Replay Evaluation** replays candidate code-change/docs-only-fix pairs from two public projects: pallets/click and encode/httpx. Start it manually in the Actions tab and inspect both reports.

The replay miner compares added and removed documentation text with source-code changes, selecting a related prior code change rather than blindly pairing the nearest commit. Its default search window is 365 days, and its workflow uses required LLM mode so API failures cannot silently fall back to deterministic checks. The candidate match rate is still not formal precision or recall: inspect the shared terms and each pair before reporting a score.

## Design and safety

- LLM output is treated as a probabilistic review, not ground truth.
- Retrieved code and documentation are untrusted input, not instructions.
- Model outputs cannot choose the file paths or line numbers cited in reports.
- Historical and ambiguous cases are sent for human review.
- Suggestions are proposals only. No automatic document edits or Git pushes occur.
- API credentials are read from environment variables and are not written to the index or repository.

See docs/LLM_AND_SEMANTIC_DETECTION.md for the semantic pipeline, configuration, and limitations. See docs/INGESTION_AND_DATA_MODEL.md for the ingestion snapshot format.

## Current limitations

- Semantic analysis depends on an API key, network access, model availability and the provider's quotas.
- Retrieval uses an in-memory BM25-style ranker plus a local embedding cache, not a hosted vector database.
- Deterministic analysis is strongest for Python scalar/configuration changes and argparse flags; generic multi-language changes are model-assisted and need validation.
- Historical replay mines candidate pairs but does not establish ground truth by itself.
- A frontend is not included in this CLI/Actions release.
