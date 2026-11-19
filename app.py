import argparse
import os
import sys
from contextlib import ExitStack
from pathlib import Path

from docuguard.drift_detector import detect_documentation_drift
from docuguard.ingestion.sources import SourceError, resolve_source
from docuguard.llm_client import LLMError, get_api_key, get_model
from docuguard.reporting import (
    render_html_report,
    render_markdown_summary,
    write_github_annotations,
    write_json_report,
    write_step_summary,
)
from docuguard.suggestion_engine import generate_suggestion


def build_parser():
    parser = argparse.ArgumentParser(
        description="Detect documentation made stale by code changes."
    )
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent,
                        help="Repository to analyse (defaults to this project).")
    docs = parser.add_mutually_exclusive_group()
    docs.add_argument(
        "--docs-path", type=Path,
        help="Optional separate local checkout containing documentation files."
    )
    docs.add_argument(
        "--docs-url",
        help="Optional HTTPS GitHub URL of a separate documentation repository."
    )
    docs.add_argument(
        "--docs-zip", type=Path,
        help="Optional ZIP archive containing the documentation source."
    )
    docs.add_argument(
        "--docs-website",
        help="Optional public static documentation website (bounded same-origin crawl)."
    )
    parser.add_argument("--docs-branch", help="Branch to clone from --docs-url.")
    parser.add_argument(
        "--llm-mode", choices=("auto", "off", "required"),
        default=os.environ.get("DOCUGUARD_LLM_MODE", "auto"),
        help="auto uses the model when an API key exists; off is deterministic; required fails without the model.",
    )
    parser.add_argument(
        "--no-embeddings", action="store_true",
        help="Use lexical retrieval instead of the embeddings API (LLM judging still runs).",
    )
    parser.add_argument("--html-out", type=Path,
                        help="Write a self-contained HTML report to this path.")
    parser.add_argument("--json-out", type=Path,
                        help="Write machine-readable findings and suggestions to this path.")
    return parser


def _manual_review_for_finding(finding):
    evidence = {
        "symbol": finding.get("symbol"),
        "old_value": finding.get("old_value"),
        "new_value": finding.get("new_value"),
        "code_file": finding["code_change"]["file"],
        "code_line": finding["code_change"].get("new_line") or finding["code_change"].get("old_line"),
        "documentation_file": finding["documentation"]["file"],
        "documentation_line": finding["documentation"]["line"],
        "confidence": finding.get("confidence")
    }
    if finding.get("option") is not None:
        evidence["option"] = finding["option"]
        evidence["option_default"] = finding.get("option_default")
    return {
        "status": "manual_review_required",
        "reason": finding.get("reason", "Historical or ambiguous documentation needs human review."),
        "evidence": evidence
    }


def main(argv=None):
    args = build_parser().parse_args(argv)
    repository = args.repo.resolve()
    if not repository.is_dir():
        print(f"Repository directory does not exist: {repository}", file=sys.stderr)
        return 2

    print("=" * 55)
    print("                  DOCUGUARD")
    print("       Documentation Drift Detection System")
    print("=" * 55)
    print("\nAnalyzing repository...\n")

    if args.llm_mode == "off":
        print("LLM: disabled (deterministic checks only)")
    elif get_api_key():
        print(f"LLM: enabled ({get_model()})")
        if not args.no_embeddings:
            print("Retrieval: embeddings + lexical ranking (cached locally)")
        else:
            print("Retrieval: lexical ranking")
    else:
        print("LLM: not configured; using deterministic checks")
        print("      Set OPENAI_API_KEY to enable semantic mapping.")

    suggestions = []
    try:
        with ExitStack() as stack:
            docs_path = None
            if args.docs_path is not None:
                docs_path = args.docs_path.expanduser().resolve()
                if not docs_path.is_dir():
                    raise SourceError(f"Documentation directory does not exist: {docs_path}")
            elif args.docs_url or args.docs_zip or args.docs_website:
                docs_path, _ = resolve_source(
                    stack,
                    github_url=args.docs_url,
                    zip_path=args.docs_zip,
                    website_url=args.docs_website,
                    branch=args.docs_branch,
                    label="docs",
                )

            findings = detect_documentation_drift(
                repository,
                docs_path,
                llm_mode=args.llm_mode,
                use_embeddings=False if args.no_embeddings else None,
            )
            for finding in findings:
                if finding.get("status") == "likely_drift":
                    suggestion = generate_suggestion(finding)
                    if suggestion is not None:
                        suggestions.append(suggestion)
                elif finding.get("status") == "needs_review":
                    suggestions.append(_manual_review_for_finding(finding))

    except (SourceError, LLMError, OSError, ValueError) as error:
        print(f"DocuGuard could not complete the analysis: {error}", file=sys.stderr)
        return 2

    likely_count = sum(f.get("status") == "likely_drift" for f in findings)
    review_count = sum(f.get("status") == "needs_review" for f in findings)

    if not findings:
        print("No documentation drift detected.")
    else:
        print(
            f"Found {likely_count} likely drift issue(s) and "
            f"{review_count} item(s) requiring manual review.\n"
        )
        for index, suggestion in enumerate(suggestions, start=1):
            evidence = suggestion["evidence"]
            print(f"ISSUE #{index}")
            print("-" * 55)
            print("Status:", suggestion["status"])
            if suggestion.get("original_sentence"):
                print("\nOutdated documentation:")
                print(suggestion["original_sentence"])
            if suggestion.get("suggested_sentence"):
                print("\nSuggested correction:")
                print(suggestion["suggested_sentence"])
            print("\nEvidence:")
            print(f"Code: {evidence['code_file']}:{evidence['code_line']}")
            print(
                f"Documentation: {evidence['documentation_file']}:"
                f"{evidence['documentation_line']}"
            )
            if evidence.get("confidence") is not None:
                print(f"Confidence: {evidence['confidence']:.0%}")
            if suggestion.get("reason"):
                print("\nNext action:")
                print(suggestion["reason"])
            if suggestion.get("explanation"):
                print("\nExplanation:")
                print(suggestion["explanation"])
            print("-" * 55)

    markdown = render_markdown_summary(findings, suggestions)
    write_github_annotations(findings)
    write_step_summary(markdown)

    if args.html_out:
        args.html_out.parent.mkdir(parents=True, exist_ok=True)
        args.html_out.write_text(
            render_html_report(findings, suggestions, repository.name),
            encoding="utf-8"
        )
        print(f"\nHTML report written to: {args.html_out}")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        write_json_report(args.json_out, findings, suggestions)
        print(f"JSON report written to: {args.json_out}")

    print("\nDocuGuard analysis completed.")
    return 1 if likely_count else 0


if __name__ == "__main__":
    sys.exit(main())
