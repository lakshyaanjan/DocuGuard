"""Command-line entry point for repository/documentation ingestion."""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import ExitStack
from pathlib import Path

from .organizer import IngestionError, ingest_project
from .sources import SourceError, resolve_source


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docuguard-ingest",
        description="Collect and organise source code, documentation and comments for DocuGuard.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    code = parser.add_mutually_exclusive_group(required=True)
    code.add_argument("--repo", type=Path, help="Path to an existing local source checkout/directory.")
    code.add_argument("--repo-url", help="HTTPS GitHub URL of a public or token-authorised repository.")
    code.add_argument("--repo-zip", type=Path, help="ZIP archive containing the source repository.")

    docs = parser.add_mutually_exclusive_group()
    docs.add_argument("--docs-path", type=Path, help="Optional separate local documentation checkout.")
    docs.add_argument("--docs-url", help="Optional separate HTTPS GitHub documentation repository.")
    docs.add_argument("--docs-zip", type=Path, help="Optional separate documentation ZIP archive.")
    docs.add_argument("--docs-website", help="Optional public static documentation website URL (same-origin HTML crawl).")

    parser.add_argument("--branch", help="Branch to clone from --repo-url.")
    parser.add_argument("--docs-branch", help="Branch to clone from --docs-url.")
    parser.add_argument("--project-name", help="Friendly project name (defaults to repository folder).")
    parser.add_argument("--output", type=Path, default=Path.cwd() / ".docuguard" / "index",
                        help="Index output root. A versioned project snapshot is created inside it.")
    parser.add_argument("--json", action="store_true", help="Print the result as JSON for scripts/web backends.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        with ExitStack() as stack:
            code_root, code_origin = resolve_source(
                stack, local_path=args.repo, github_url=args.repo_url,
                zip_path=args.repo_zip, branch=args.branch, label="repo",
            )
            if any(value is not None for value in (args.docs_path, args.docs_url, args.docs_zip, args.docs_website)):
                docs_root, docs_origin = resolve_source(
                    stack, local_path=args.docs_path, github_url=args.docs_url,
                    zip_path=args.docs_zip, website_url=args.docs_website,
                    branch=args.docs_branch, label="docs",
                )
            else:
                docs_root, docs_origin = None, code_origin

            result = ingest_project(
                repo_path=code_root,
                docs_path=docs_root,
                project_name=args.project_name,
                output_dir=args.output,
                code_origin=code_origin,
                docs_origin=docs_origin,
            )

        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print("DocuGuard ingestion completed")
            print(f"Project:   {result.project_id}")
            print(f"Snapshot:  {result.snapshot_id}")
            print(f"Files:     {result.file_count}")
            print(f"Chunks:    {result.chunk_count}")
            print(f"Summaries: {result.summary_count}")
            print(f"Skipped:   {result.skipped_count}")
            print(f"Output:    {result.output_dir}")
            print(f"Manifest:  {result.manifest_path}")
            print("\nNo embeddings or LLM calls were made.")
        return 0
    except (SourceError, IngestionError, OSError, ValueError) as error:
        print(f"DocuGuard ingestion error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
