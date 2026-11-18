"""Replay likely documentation-drift fixes from a repository's Git history.

This is a candidate-mining evaluation tool, not a ground-truth oracle: a
documentation-only commit near a code commit may fix drift, but it may also
contain unrelated edits. The report therefore labels its metric as a candidate
match rate rather than formal recall or precision.
"""

import argparse
import json
import os
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
    # Skip root and merge commits: the replay pair needs one unambiguous parent.
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


def find_replay_candidates(
    repository,
    head_ref="HEAD",
    window_days=30,
    max_pairs=20,
    max_history_commits=1000
):
    """Pair docs-only commits with the nearest prior source-changing commit."""
    repository = Path(repository).resolve()
    commits = run_git(repository, "rev-list", "--first-parent", head_ref).splitlines()
    commits = commits[:max_history_commits]
    window_seconds = window_days * 24 * 60 * 60
    candidates = []

    for index, docs_sha in enumerate(commits):
        docs_files = changed_files(repository, docs_sha)
        if not is_documentation_only(docs_files):
            continue

        docs_time = commit_timestamp(repository, docs_sha)

        for code_sha in commits[index + 1:]:
            code_time = commit_timestamp(repository, code_sha)
            age = docs_time - code_time

            if age < 0:
                continue
            if age > window_seconds:
                break

            code_files = changed_files(repository, code_sha)
            if not has_source_changes(code_files):
                continue

            try:
                parent_sha = commit_parent(repository, code_sha)
            except ValueError:
                continue

            candidates.append({
                "code_commit": code_sha,
                "code_parent": parent_sha,
                "code_files": code_files,
                "docs_commit": docs_sha,
                "docs_files": docs_files,
                "gap_seconds": age
            })
            break

        if len(candidates) >= max_pairs:
            break

    return candidates


def replay_candidate(repository, candidate, timeout_seconds=120):
    """Run DocuGuard against a temporary worktree at the original code change."""
    repository = Path(repository).resolve()

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

            # Run the current DocuGuard implementation against the historical
            # target worktree. The target repository does not contain DocuGuard.
            app_path = Path(__file__).resolve().parents[1] / "app.py"
            if not app_path.is_file():
                raise RuntimeError("Could not locate the DocuGuard app.py entry point.")

            command = [
                sys.executable,
                str(app_path),
                "--repo", str(worktree),
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
                raise RuntimeError(
                    f"DocuGuard exited with {process.returncode}: "
                    f"{process.stderr[-1500:]}"
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

            return {
                **candidate,
                "outcome": "caught" if matched else "missed",
                "finding_count": len(findings),
                "matched_finding_count": len(matched),
                "unmatched_finding_count": len(unmatched),
                "matched_findings": matched,
                "unmatched_findings": unmatched
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
    """Render a compact candidate-replay report."""
    caught = sum(item.get("outcome") == "caught" for item in results)
    missed = sum(item.get("outcome") == "missed" for item in results)
    errors = sum(item.get("outcome") == "error" for item in results)
    rate = (caught / (caught + missed)) if caught + missed else 0.0

    lines = [
        "# DocuGuard historical replay",
        "",
        f"**Repository:** {repository_name}",
        f"**Candidate pairs:** {len(results)}",
        f"**Caught:** {caught} · **Missed:** {missed} · **Replay errors:** {errors}",
        f"**Candidate match rate:** {rate:.1%}",
        "",
        "> This is a candidate match rate, not formal recall/precision. "
        "A docs-only commit near a code change is a heuristic and may be unrelated.",
        ""
    ]

    for index, item in enumerate(results, start=1):
        lines.extend([
            f"## Candidate {index}: {item.get('outcome', 'unknown')}",
            "",
            f"- Code commit: {item.get('code_commit', 'n/a')}",
            f"- Follow-up docs commit: {item.get('docs_commit', 'n/a')}",
            f"- Code files: {', '.join(item.get('code_files', []))}",
            f"- Documentation files: {', '.join(item.get('docs_files', []))}",
            f"- Findings: {item.get('finding_count', 0)} "
            f"(matched to later documentation files: {item.get('matched_finding_count', 0)})",
            ""
        ])
        if item.get("error"):
            lines.append(f"Error: {item['error']}")
            lines.append("")

    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Replay likely documentation fixes against the earlier code state."
    )
    parser.add_argument("--repo", type=Path, required=True, help="Path to a full Git clone.")
    parser.add_argument("--head", default="HEAD", help="History ref to scan (default: HEAD).")
    parser.add_argument("--window-days", type=int, default=30,
                        help="Maximum delay between code change and docs-only fix.")
    parser.add_argument("--max-pairs", type=int, default=20,
                        help="Maximum candidate pairs to replay.")
    parser.add_argument("--max-history-commits", type=int, default=1000,
                        help="Maximum first-parent commits to inspect.")
    parser.add_argument("--timeout", type=int, default=120,
                        help="Seconds allowed for one historical DocuGuard run.")
    parser.add_argument("--output", type=Path, default=Path("history-replay-report.json"),
                        help="JSON report output path.")
    parser.add_argument("--markdown-out", type=Path, default=Path("history-replay-report.md"),
                        help="Markdown summary output path.")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    repository = args.repo.resolve()

    if args.window_days < 1 or args.max_pairs < 1 or args.max_history_commits < 1:
        raise SystemExit("window-days, max-pairs and max-history-commits must be positive.")

    candidates = find_replay_candidates(
        repository,
        head_ref=args.head,
        window_days=args.window_days,
        max_pairs=args.max_pairs,
        max_history_commits=args.max_history_commits
    )

    results = []
    for candidate in candidates:
        try:
            results.append(replay_candidate(repository, candidate, args.timeout))
        except Exception as error:
            results.append({
                **candidate,
                "outcome": "error",
                "error": str(error),
                "finding_count": 0,
                "matched_finding_count": 0,
                "unmatched_finding_count": 0
            })

    output_payload = {
        "repository": str(repository),
        "candidate_count": len(results),
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

    caught = sum(item.get("outcome") == "caught" for item in results)
    missed = sum(item.get("outcome") == "missed" for item in results)
    errors = sum(item.get("outcome") == "error" for item in results)

    print(markdown)
    print(f"JSON report: {args.output}")
    print(f"Markdown report: {args.markdown_out}")

    if not candidates:
        print(
            "No candidate code-change/docs-only-fix pairs were found in the "
            "selected history window. Try a larger --window-days or --max-history-commits."
        )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
