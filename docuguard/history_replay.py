"""Replay relevant historical code/documentation changes from Git history.

The miner only pairs a docs-only commit with a prior source commit when their
changed text shares meaningful identifiers or terms. This reduces the common
false pairing of unrelated nearby commits. The result is still a candidate
benchmark, not formal precision/recall: maintainers must inspect each pair.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


DOCUMENTATION_EXTENSIONS = {".md", ".markdown", ".rst", ".html", ".htm"}
SOURCE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".go", ".rs", ".java", ".c", ".h", ".cc", ".cpp",
    ".cs", ".php", ".rb", ".swift", ".kt", ".scala", ".sh"
}
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")
STOP_WORDS = {
    "the", "and", "for", "from", "with", "that", "this", "when", "then",
    "into", "your", "will", "should", "could", "would", "have", "has",
    "are", "was", "were", "been", "being", "use", "used", "using", "new",
    "old", "true", "false", "none", "null", "self", "return", "class",
    "def", "const", "let", "var", "import", "export", "function", "if",
    "else", "elif", "while", "for", "try", "except", "raise", "with",
    "as", "is", "in", "on", "of", "to", "a", "an", "or", "by", "it",
    "add", "added", "change", "changed", "update", "updated", "fix", "fixed",
    "version", "test", "tests", "docs", "documentation", "readme", "changelog",
    "default", "support", "supports", "using", "example", "examples",
}


def run_git(repository, *arguments, check=True):
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        text=True
    )
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Git command failed.")
    return result.stdout.strip()


def changed_files(repository, commit_sha):
    parent_line = run_git(repository, "rev-list", "--parents", "-n", "1", commit_sha)
    parents = parent_line.split()[1:]
    if len(parents) != 1:
        return []
    output = run_git(
        repository, "diff-tree", "--no-commit-id", "--name-only", "-r", commit_sha
    )
    return [line.strip().replace("\\", "/") for line in output.splitlines() if line.strip()]


def is_documentation_only(paths):
    return bool(paths) and all(
        Path(path).suffix.lower() in DOCUMENTATION_EXTENSIONS
        for path in paths
    )


def has_source_changes(paths):
    return any(
        Path(path).suffix.lower() in SOURCE_EXTENSIONS
        for path in paths
    )


def commit_timestamp(repository, commit_sha):
    value = run_git(repository, "show", "-s", "--format=%ct", commit_sha)
    return int(value)


def commit_parent(repository, commit_sha):
    line = run_git(repository, "rev-list", "--parents", "-n", "1", commit_sha)
    parents = line.split()[1:]
    if len(parents) != 1:
        raise ValueError(f"Commit {commit_sha} does not have exactly one parent.")
    return parents[0]


def changed_patch(repository, commit_sha, paths):
    """Return only added/removed diff text for the supplied paths."""
    if not paths:
        return ""
    return run_git(
        repository,
        "show", "--format=", "--no-ext-diff", "--unified=0",
        commit_sha, "--", *paths
    )


def changed_text_tokens(patch_text):
    """Extract meaningful exact identifiers and words from changed diff lines."""
    tokens = set()
    for line in patch_text.splitlines():
        if not line.startswith(("+", "-")) or line.startswith(("+++", "---")):
            continue
        for raw in TOKEN_RE.findall(line[1:]):
            normalized = raw.lower()
            if normalized in STOP_WORDS:
                continue
            tokens.add(normalized)
            # Keep both the complete snake_case identifier and its components.
            # The complete identifier receives the stronger relevance weight.
            if "_" in normalized:
                tokens.update(
                    part for part in normalized.split("_")
                    if len(part) >= 3 and part not in STOP_WORDS
                )
    return tokens


def score_change_relevance(code_tokens, docs_tokens):
    """Score shared changed terms; exact compound identifiers count more."""
    shared = code_tokens & docs_tokens
    ordered = sorted(shared, key=lambda item: (-("_" in item), -len(item), item))
    score = sum(3 if "_" in term else 1 for term in shared)
    return score, ordered


def find_replay_candidates(
    repository,
    head_ref="HEAD",
    window_days=365,
    max_pairs=20,
    max_history_commits=4000,
    min_relevance_score=2
):
    """Pair docs fixes with the most textually related prior source change.

    The nearest prior source commit is not automatically assumed to be related.
    Changed-line token overlap is used to select a relevant source commit first;
    ties prefer the temporally closest commit.
    """
    repository = Path(repository).resolve()
    commits = run_git(repository, "rev-list", "--first-parent", head_ref).splitlines()
    commits = commits[:max_history_commits]
    window_seconds = window_days * 24 * 60 * 60
    candidates = []
    timestamp_cache = {}
    files_cache = {}
    source_token_cache = {}

    def files_for(sha):
        if sha not in files_cache:
            files_cache[sha] = changed_files(repository, sha)
        return files_cache[sha]

    def timestamp_for(sha):
        if sha not in timestamp_cache:
            timestamp_cache[sha] = commit_timestamp(repository, sha)
        return timestamp_cache[sha]

    for index, docs_sha in enumerate(commits):
        docs_files = files_for(docs_sha)
        if not is_documentation_only(docs_files):
            continue

        docs_tokens = changed_text_tokens(changed_patch(repository, docs_sha, docs_files))
        if not docs_tokens:
            continue
        docs_time = timestamp_for(docs_sha)
        best = None

        for code_sha in commits[index + 1:]:
            code_time = timestamp_for(code_sha)
            age = docs_time - code_time
            if age < 0:
                continue
            if age > window_seconds:
                break

            all_code_files = files_for(code_sha)
            source_files = [
                path for path in all_code_files
                if Path(path).suffix.lower() in SOURCE_EXTENSIONS
            ]
            if not source_files:
                continue

            if code_sha not in source_token_cache:
                patch = changed_patch(repository, code_sha, source_files)
                source_token_cache[code_sha] = changed_text_tokens(patch)
            score, shared_terms = score_change_relevance(
                source_token_cache[code_sha], docs_tokens
            )
            if score < min_relevance_score:
                continue

            try:
                parent_sha = commit_parent(repository, code_sha)
            except ValueError:
                continue

            candidate = {
                "code_commit": code_sha,
                "code_parent": parent_sha,
                "code_files": source_files,
                "docs_commit": docs_sha,
                "docs_files": docs_files,
                "gap_seconds": age,
                "relevance_score": score,
                "shared_terms": shared_terms[:20],
            }
            if (
                best is None
                or candidate["relevance_score"] > best["relevance_score"]
                or (
                    candidate["relevance_score"] == best["relevance_score"]
                    and candidate["gap_seconds"] < best["gap_seconds"]
                )
            ):
                best = candidate

        if best is not None:
            candidates.append(best)
        if len(candidates) >= max_pairs:
            break

    return candidates


def replay_candidate(repository, candidate, timeout_seconds=120, llm_mode=None):
    """Run DocuGuard at the original code-change state and retain run evidence."""
    repository = Path(repository).resolve()
    mode = (llm_mode or os.environ.get("DOCUGUARD_LLM_MODE", "auto")).lower()
    if mode not in {"auto", "off", "required"}:
        raise ValueError("llm_mode must be one of: auto, off, required.")

    with tempfile.TemporaryDirectory(prefix="docuguard-history-") as temporary:
        temporary_path = Path(temporary)
        worktree = temporary_path / "worktree"
        json_report = temporary_path / "docuguard-report.json"
        added_worktree = False

        try:
            run_git(repository, "worktree", "add", "--detach", str(worktree), candidate["code_commit"])
            added_worktree = True

            environment = os.environ.copy()
            environment["DOCUGUARD_BASE_REF"] = candidate["code_parent"]
            environment["DOCUGUARD_LLM_MODE"] = mode

            app_path = Path(__file__).resolve().parents[1] / "app.py"
            if not app_path.is_file():
                raise RuntimeError("Could not locate the DocuGuard app.py entry point.")

            command = [
                sys.executable,
                str(app_path),
                "--repo", str(worktree),
                "--llm-mode", mode,
                "--json-out", str(json_report)
            ]
            process = subprocess.run(
                command,
                cwd=worktree,
                env=environment,
                capture_output=True,
                text=True,
                timeout=timeout_seconds
            )

            if process.returncode not in (0, 1):
                details = (process.stderr or process.stdout)[-2000:]
                raise RuntimeError(
                    f"DocuGuard exited with {process.returncode}: {details}"
                )
            if not json_report.is_file():
                raise RuntimeError("DocuGuard did not produce its JSON report.")

            payload = json.loads(json_report.read_text(encoding="utf-8"))
            findings = payload.get("findings", [])
            fixed_docs = set(candidate["docs_files"])
            matched = [
                finding for finding in findings
                if finding.get("documentation", {}).get("file") in fixed_docs
            ]
            unmatched = [
                finding for finding in findings
                if finding.get("documentation", {}).get("file") not in fixed_docs
            ]
            model_line = re.search(r"LLM: enabled \(([^)]+)\)", process.stdout)
            fallback_detected = "LLM layer was unavailable" in (process.stderr or "")

            return {
                **candidate,
                "outcome": "caught" if matched else "missed",
                "finding_count": len(findings),
                "matched_finding_count": len(matched),
                "unmatched_finding_count": len(unmatched),
                "matched_findings": matched,
                "unmatched_findings": unmatched,
                "llm_mode": mode,
                "llm_model": model_line.group(1) if model_line else None,
                "llm_fallback_detected": fallback_detected,
                "llm_semantic_finding_count": sum(
                    finding.get("analysis_source") == "llm_semantic"
                    for finding in findings
                ),
            }

        finally:
            if added_worktree:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(worktree)],
                    cwd=repository,
                    capture_output=True,
                    text=True
                )
                subprocess.run(
                    ["git", "worktree", "prune"],
                    cwd=repository,
                    capture_output=True,
                    text=True
                )


def render_replay_markdown(results, repository_name):
    """Render a transparent candidate replay report."""
    caught = sum(item.get("outcome") == "caught" for item in results)
    missed = sum(item.get("outcome") == "missed" for item in results)
    errors = sum(item.get("outcome") == "error" for item in results)
    rate = (caught / (caught + missed)) if caught + missed else 0.0

    lines = [
        "# DocuGuard historical replay",
        "",
        f"**Repository:** {repository_name}",
        f"**Relevant candidate pairs:** {len(results)}",
        f"**Caught:** {caught} · **Missed:** {missed} · **Replay errors:** {errors}",
        f"**Candidate match rate:** {rate:.1%}",
        "",
        "> Candidate match rate is not formal precision or recall. Changed-text overlap",
        "> improves pairing relevance, but each pair still needs maintainer verification.",
        ""
    ]

    for index, item in enumerate(results, start=1):
        lines.extend([
            f"## Candidate {index}: {item.get('outcome', 'unknown')}",
            "",
            f"- Code commit: {item.get('code_commit', 'n/a')}",
            f"- Follow-up docs commit: {item.get('docs_commit', 'n/a')}",
            f"- Gap: {item.get('gap_seconds', 0) // 86400} days",
            f"- Relevance score: {item.get('relevance_score', 0)}",
            f"- Shared changed terms: {', '.join(item.get('shared_terms', [])) or 'none'}",
            f"- Code files: {', '.join(item.get('code_files', []))}",
            f"- Documentation files: {', '.join(item.get('docs_files', []))}",
            f"- Findings: {item.get('finding_count', 0)} "
            f"(matched to later documentation files: {item.get('matched_finding_count', 0)})",
            f"- LLM mode: {item.get('llm_mode', 'unknown')}",
            f"- LLM model: {item.get('llm_model') or 'not reported'}",
            f"- LLM fallback warning: {'yes' if item.get('llm_fallback_detected') else 'no'}",
            f"- Semantic findings: {item.get('llm_semantic_finding_count', 0)}",
            ""
        ])
        if item.get("error"):
            lines.append(f"Error: {item['error']}")
            lines.append("")

    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Replay relevant historical code/documentation changes."
    )
    parser.add_argument("--repo", type=Path, required=True, help="Path to a full Git clone.")
    parser.add_argument("--head", default="HEAD", help="History ref to scan (default: HEAD).")
    parser.add_argument("--window-days", type=int, default=365,
                        help="Maximum delay between a source change and a docs-only follow-up.")
    parser.add_argument("--max-pairs", type=int, default=20,
                        help="Maximum relevant candidate pairs to replay.")
    parser.add_argument("--max-history-commits", type=int, default=4000,
                        help="Maximum first-parent commits to inspect.")
    parser.add_argument("--min-relevance-score", type=int, default=2,
                        help="Minimum shared changed-text score required for a candidate.")
    parser.add_argument("--llm-mode", choices=("auto", "off", "required"),
                        default=os.environ.get("DOCUGUARD_LLM_MODE", "auto"),
                        help="LLM mode passed explicitly to each historical replay.")
    parser.add_argument("--timeout", type=int, default=180,
                        help="Seconds allowed for one historical DocuGuard run.")
    parser.add_argument("--output", type=Path, default=Path("history-replay-report.json"),
                        help="JSON report output path.")
    parser.add_argument("--markdown-out", type=Path, default=Path("history-replay-report.md"),
                        help="Markdown summary output path.")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    repository = args.repo.resolve()

    if (
        args.window_days < 1 or args.max_pairs < 1
        or args.max_history_commits < 1 or args.min_relevance_score < 1
    ):
        raise SystemExit(
            "window-days, max-pairs, max-history-commits and min-relevance-score must be positive."
        )

    candidates = find_replay_candidates(
        repository,
        head_ref=args.head,
        window_days=args.window_days,
        max_pairs=args.max_pairs,
        max_history_commits=args.max_history_commits,
        min_relevance_score=args.min_relevance_score,
    )

    results = []
    for candidate in candidates:
        try:
            results.append(
                replay_candidate(repository, candidate, args.timeout, args.llm_mode)
            )
        except Exception as error:
            results.append({
                **candidate,
                "outcome": "error",
                "error": str(error),
                "finding_count": 0,
                "matched_finding_count": 0,
                "unmatched_finding_count": 0,
                "llm_mode": args.llm_mode,
            })

    output_payload = {
        "repository": str(repository),
        "candidate_count": len(results),
        "llm_mode": args.llm_mode,
        "results": results
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output_payload, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8"
    )

    markdown = render_replay_markdown(results, repository.name)
    args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_out.write_text(markdown + "\n", encoding="utf-8")

    errors = sum(item.get("outcome") == "error" for item in results)
    print(markdown)
    print(f"JSON report: {args.output}")
    print(f"Markdown report: {args.markdown_out}")

    if not candidates:
        print(
            "No relevant changed-text pairs were found. Try a larger "
            "--window-days or --max-history-commits, or review the source/docs history manually."
        )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
