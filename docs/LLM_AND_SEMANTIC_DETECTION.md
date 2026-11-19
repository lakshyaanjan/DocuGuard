# DocuGuard semantic detection and LLM setup

DocuGuard has two complementary detection paths:

1. **Deterministic rules** identify literal Python scalar/configuration changes and removed command-line flags. These checks work offline and do not require an API key.
2. **Semantic retrieval and LLM review** connect changed source files to relevant documentation passages, then ask a model whether the code change actually made those passages inaccurate.

## What happens during a pull request

1. Git diff extracts added and removed source lines with their original line numbers.
2. DocuGuard extracts documentation sentences and Markdown table rows with file/line provenance.
3. A BM25-style lexical ranker finds likely related passages. If an API key is configured, embeddings can improve semantic retrieval.
4. Documentation embeddings are cached outside the repository. The cache key includes the model name and content hash, so unchanged passages can reuse their vectors.
5. For each changed source file, a bounded shortlist of up to eight documentation passages and the exact code diff is sent to the configured Chat Completions model.
6. The model returns structured classifications: likely_drift, no_drift, needs_review, or unrelated.
7. DocuGuard validates the returned candidate index and attaches the original file path and line number from its own extraction. The model is not trusted to invent citations.
8. High-confidence drift may receive a suggested replacement sentence. Historical or ambiguous passages are routed to a human reviewer. DocuGuard never changes files automatically.

The default limits are eight changed files and eight candidate passages per changed file, keeping model input bounded.

## Configure Google AI Studio (Gemini)

Google AI Studio provides an OpenAI-compatible API for Chat Completions and embeddings. DocuGuard calls those endpoints rather than the OpenAI Responses API. Create a key in https://aistudio.google.com/apikey.

PowerShell (current terminal only):

~~~powershell
$secureKey = Read-Host "Paste your Gemini API key" -AsSecureString
$env:GEMINI_API_KEY = ([System.Net.NetworkCredential]::new("", $secureKey)).Password
Remove-Variable secureKey

$env:DOCUGUARD_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
$env:DOCUGUARD_LLM_MODEL = "gemini-3.5-flash-lite"
$env:DOCUGUARD_EMBEDDING_MODEL = "gemini-embedding-2-preview"
$env:DOCUGUARD_USE_EMBEDDINGS = "false"

python examples/run_demo.py --llm-mode required --no-embeddings
~~~

This runs the Gemini judge with lexical retrieval and makes no embeddings requests. The `gemini-3.5-flash-lite` model was smoke-tested with this repository's Chat Completions client. Check the AI Studio Rate Limit and Usage pages for the active project's exact quotas, and review Google's data-use terms before sending private or sensitive source code.

To enable Gemini embeddings, set DOCUGUARD_USE_EMBEDDINGS to true. The configured OpenAI-compatible embedding model is gemini-embedding-2-preview. Its availability and quota depend on the AI Studio project.

## Configure another OpenAI-compatible provider

The API key is read from the environment and is never written to the repository. For OpenAI, set OPENAI_API_KEY and use the default API base/model. For another compatible provider, set DOCUGUARD_OPENAI_BASE_URL and DOCUGUARD_LLM_MODEL to its endpoint and a model that supports Chat Completions structured outputs. Set DOCUGUARD_EMBEDDING_MODEL if that provider's embedding model differs.

For GitHub Actions, add the key as a repository secret. For Gemini, create a secret named GEMINI_API_KEY and repository variables named DOCUGUARD_OPENAI_BASE_URL and DOCUGUARD_LLM_MODEL with the Gemini values shown above.

## Analysis modes

- --llm-mode auto (default): use the semantic layer when an API key is configured; on API failure retain deterministic results and emit a warning.
- --llm-mode off: deterministic checks only; no model API requests.
- --llm-mode required: fail clearly when the key or model service is unavailable. Use this mode when an evaluation must prove the LLM path ran.
- --no-embeddings: use lexical retrieval while keeping the LLM judge enabled.

## Configuration

| Environment variable | Default | Purpose |
|---|---|---|
| OPENAI_API_KEY | unset | OpenAI API credential |
| GEMINI_API_KEY | unset | Google AI Studio Gemini API credential |
| GOOGLE_API_KEY | unset | Alternative Google API credential name |
| DOCUGUARD_OPENAI_API_KEY | unset | Alternative API key name |
| DOCUGUARD_OPENAI_BASE_URL | https://api.openai.com/v1 | OpenAI-compatible API base URL |
| DOCUGUARD_LLM_MODEL | gpt-6.2-astra | Chat Completions model |
| DOCUGUARD_EMBEDDING_MODEL | text-embedding-3-small | Embeddings model |
| DOCUGUARD_USE_EMBEDDINGS | true | Enable/disable embedding retrieval |
| DOCUGUARD_CACHE_DIR | ~/.cache/docuguard | Local embedding cache |
| DOCUGUARD_LLM_MODE | auto | Default analysis mode |

The client uses Python's standard library and adds no package dependency. It calls the Chat Completions endpoint with JSON Schema structured output and the embeddings endpoint for vectors. Use models available to your API account; provider quotas and model availability can change.

## Separate documentation sources

Documentation can live outside the code repository:

~~~powershell
python app.py --repo ..\source --docs-path ..\documentation
python app.py --repo ..\source --docs-url https://github.com/owner/docs --docs-branch main
python app.py --repo ..\source --docs-zip .\docs.zip
python app.py --repo ..\source --docs-website https://docs.example.com/
~~~

The GitHub source resolver supports public repositories and private repositories when DOCUGUARD_GITHUB_TOKEN is configured with read-only access. Website crawling is restricted to bounded, public, same-origin static HTML. It rejects private-address resolutions and cross-origin redirects. JavaScript-rendered and authenticated sites are not supported.

## Run the end-to-end demonstration

From the DocuGuard repository root:

~~~powershell
python examples/run_demo.py
~~~

The demo creates a temporary Git repository, changes a Python default from 8000 to 9090, leaves the README stale, and runs DocuGuard against the change. It also includes a clearly historical passage so the report can show the distinction between a current instruction and a historical note. The demo writes a self-contained HTML report and a JSON report under demo-output/.

For a fully offline demonstration:

~~~powershell
python examples/run_demo.py --llm-mode off
~~~

## Historical replay

The existing historical replay workflow can be started from GitHub Actions for the two public projects configured in .github/workflows/historical-replay.yml (pallets/click and encode/httpx). Open the **Actions** tab, select **DocuGuard Historical Replay Evaluation**, choose **Run workflow**, and inspect both generated reports.

The replay tool mines likely code-change/documentation-fix pairs. Its candidate match rate is a heuristic, not formal recall or precision: a docs-only commit near a source change may be unrelated. Inspect the listed commit pairs and findings before presenting any score.

## Limitations and responsible use

- Model judgments are probabilistic. Suggested text is a proposal for maintainer review, not an automatic edit.
- An absent key, rate limit, network failure, or unsupported model in auto mode leaves deterministic checks available. Required mode fails rather than silently claiming semantic analysis happened.
- Retrieval is per-run in-memory ranking plus a local embedding cache. This is not a hosted vector database or full cross-run incremental code index.
- The ingestion snapshots remain the provenance-preserving source-data layer. Their current summaries are extractive, not represented as model-generated summaries.
- The history replay tool does not establish ground truth. Do not describe its candidate match rate as measured precision or recall.
- DocuGuard never commits, pushes, or automatically edits documentation.
