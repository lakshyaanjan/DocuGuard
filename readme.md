# DocuGuard

**Catch documentation that a code change made wrong.**

DocuGuard is a GitHub Actions check that compares changed Python code with Markdown, reStructuredText and HTML documentation. It reports likely stale passages with the documentation location, corresponding code change, confidence and (when safe) a proposed correction.

## Current capabilities

- Renamed or removed literal argparse command-line flags.
- Changed simple Python scalar defaults: integers, decimals, strings, booleans and negative numbers.
- Added or removed keys in simple, single-line Python dictionary configuration assignments, when existing entries establish a relationship to the documentation.
- Markdown table rows are extracted with source line numbers.
- Historical references and low-confidence matches are routed for human review.
- Suggestions only replace a unique, complete value. DocuGuard does not edit documentation automatically.

## Run locally

Requirements: Python 3.10+ and Git.

    git clone https://github.com/lakshyaanjan/DocuGuard.git
    cd DocuGuard
    python -m unittest discover -s tests -v
    python app.py

Generate reports:

    python app.py --html-out docuguard-report.html --json-out docuguard-report.json

Open docuguard-report.html in a browser for a self-contained responsive report. To analyse another checked-out Git repository, pass --repo PATH. If the code and docs are in different local checkouts, pass both --repo PATH and --docs-path PATH.

## GitHub Actions user experience

The pull-request workflow runs tests, analyses changes against the PR base, writes inline annotations to affected documentation lines, publishes a Markdown job summary, and uploads a downloadable HTML/JSON report artifact. Likely drift fails the check; historical or ambiguous references are visible as review notices without automatically failing the PR.

## How it works

1. Git diff identifies added and removed source lines.
2. Python AST parsing extracts changed assignments; an argparse analyser extracts literal CLI flags.
3. The documentation crawler discovers supported docs. The extractor keeps prose and Markdown table rows with line numbers while ignoring fenced code blocks.
4. The relationship engine combines identifier terms, a small explainable terminology map, value evidence and a check for explicitly named unrelated services.
5. The drift detector separates likely drift from historical references.
6. The suggestion engine proposes only safe literal replacements; ambiguous dictionary-option table changes require a maintainer to add or remove a row manually.

## Separate documentation checkout

DocuGuard can read documentation from a different local checkout:

    python app.py --repo ../project-source --docs-path ../project-docs --html-out report.html

For a private documentation repository in GitHub Actions, add a checkout step for that repository and provide an appropriately scoped token through repository secrets. Do not hard-code a token in the workflow. Remote websites are not crawled directly; check out or export their source files first.

## Historical replay

The history replay command finds docs-only commits with a nearby earlier source change, checks out the original code-change commit in a temporary Git worktree, and runs the current DocuGuard against that historical code state:

    python -m docuguard.history_replay --repo ../pallets-click --window-days 30 --max-pairs 20
    python -m docuguard.history_replay --repo ../httpx --window-days 30 --max-pairs 20

It writes JSON and Markdown reports. The reported candidate match rate is a heuristic, not formal recall or precision: a docs-only commit near a code change is not guaranteed to be a drift fix. Review candidate pairs and findings before presenting the metric.

## Run the public historical-replay evaluation

Open the GitHub **Actions** tab and select **DocuGuard Historical Replay Evaluation**. Choose **Run workflow** and select the time window and candidate limit. The workflow checks out full Git history for `pallets/click` and `encode/httpx`, runs the replay tool against both projects, writes a combined Actions summary, and uploads the JSON/Markdown reports as an artifact.

The report's candidate match rate is a heuristic, not formal recall or precision. Inspect the listed code/docs commit pairs before citing any metric. A docs-only commit near a code change may be unrelated.

## Limitations

- Python scalar assignments and configuration dictionaries currently need to be simple assignments on changed lines. Dictionary option detection currently supports literal dictionaries on one line.
- CLI extraction focuses on literal positional strings passed to argparse.add_argument.
- Docs are crawled from the same checked-out repository. Separate documentation repositories and remote websites are not indexed.
- Semantic embeddings, persistent/incremental indexing and broad language support are not implemented.
- The terminology map is small and explainable; it is not general natural-language understanding.
- Historical PR replay and evaluation on two or more external repositories remain future work.

## Safety

- DocuGuard never commits or edits documentation automatically.
- It does not post comments to third-party repositories.
- Every finding includes documentation and code evidence.
- Low-confidence and historical cases are routed to maintainers.
- HTML and JSON reports remain local or as GitHub Actions artifacts.

## Project layout

    docuguard/
      cli_analyzer.py
      code_indexer.py
      content_extractor.py
      document_crawler.py
      drift_detector.py
      git_analyzer.py
      relationship_engine.py
      reporting.py
      suggestion_engine.py
      value_utils.py
    tests/
    .github/workflows/docuguard.yml
    app.py

Add the license chosen by the project maintainers before public release.
## Ingest a project for future RAG analysis

DocuGuard now includes a separate ingestion prototype. It can read a local checkout, an HTTPS GitHub repository, or a ZIP archive, and can take documentation from the same or a separate source:

```bash
python -m docuguard.ingestion --repo ../my-project --project-name MyProject
python -m docuguard.ingestion --repo ../my-project --docs-path ../my-project-docs
python -m docuguard.ingestion --repo-url https://github.com/owner/project --branch main
python -m docuguard.ingestion --repo-zip ./source.zip --docs-zip ./docs.zip
python -m docuguard.ingestion --repo ../my-project --docs-website https://docs.example.com/
```

The default output is `.docuguard/index/<project_id>/<snapshot_id>/`, containing `manifest.json`, `files.jsonl`, `chunks.jsonl`, `summaries.jsonl` and `project_summary.json`. Chunks preserve file paths, line ranges, source commit IDs and content hashes. Markdown/RST/HTML prose, tables and code examples are extracted; public static documentation sites can be crawled with a bounded same-origin HTML fetch; Python functions, classes, assignments, comments and docstrings are indexed; common non-Python source comments and bounded code blocks are collected on a best-effort basis.

Per-file summaries are currently extractive, not AI-generated. No embeddings, vector database or LLM are used yet. See [the ingestion/data model guide](docs/INGESTION_AND_DATA_MODEL.md) for the storage schema, safety limits and future webpage/RAG integration contract.
