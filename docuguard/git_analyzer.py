
import os
import subprocess
from pathlib import Path
import json


def resolve_base_ref(repo_path, base_ref="HEAD"):
    """Resolve the Git reference used as the comparison base."""

    if base_ref != "HEAD":
        return base_ref

    configured_ref = os.environ.get("DOCUGUARD_BASE_REF")

    if not configured_ref:
        return base_ref

    result = subprocess.run(
        [
            "git",
            "rev-parse",
            "--verify",
            f"{configured_ref}^{{commit}}"
        ],
        cwd=repo_path,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Could not resolve comparison base "
            f"'{configured_ref}': {result.stderr}"
        )

    return result.stdout.strip()


def get_git_diff(repo_path, base_ref="HEAD"):
    """Get changes between the comparison base and working tree."""

    base_ref = resolve_base_ref(repo_path, base_ref)

    result = subprocess.run(
        [
            "git",
            "diff",
            "--no-ext-diff",
            "--unified=0",
            base_ref,
            "--"
        ],
        cwd=repo_path,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr)

    return result.stdout


def parse_git_diff(diff_text):
    """Extract added and removed lines from a Git diff."""

    files = []
    current_file = None
    old_line = 0
    new_line = 0

    for line in diff_text.splitlines():

        if line.startswith("diff --git "):
            current_file = {
                "file": None,
                "added_lines": [],
                "removed_lines": []
            }
            files.append(current_file)

        elif line.startswith("+++ "):
            path = line[4:]

            if path != "/dev/null":
                current_file["file"] = path[2:]

        elif line.startswith("@@ "):
            parts = line.split("@@")[1].strip().split()

            old_line = int(parts[0].split(",")[0][1:])
            new_line = int(parts[1].split(",")[0][1:])

        elif line.startswith("+") and not line.startswith("+++"):
            current_file["added_lines"].append({
                "line": new_line,
                "content": line[1:]
            })
            new_line += 1

        elif line.startswith("-") and not line.startswith("---"):
            current_file["removed_lines"].append({
                "line": old_line,
                "content": line[1:]
            })
            old_line += 1

        elif line.startswith(" "):
            old_line += 1
            new_line += 1

    return files


def analyze_repository(repo_path, base_ref="HEAD"):
    base_ref = resolve_base_ref(repo_path, base_ref)

    diff = get_git_diff(repo_path, base_ref)

    return {
        "base": base_ref,
        "files": parse_git_diff(diff)
    }


if __name__ == "__main__":

    repository = Path(__file__).resolve().parent.parent

    changes = analyze_repository(repository)

    print(json.dumps(changes, indent=4))
