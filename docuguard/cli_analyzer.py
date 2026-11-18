
import ast
import subprocess
from pathlib import Path

from .git_analyzer import analyze_repository, resolve_base_ref


def extract_cli_flags(source):
    """Extract argparse command-line flags from Python source."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    flags = []

    for node in ast.walk(tree):

        if not isinstance(node, ast.Call):
            continue

        function = node.func

        if not (
            isinstance(function, ast.Attribute)
            and function.attr == "add_argument"
        ):
            continue

        for argument in node.args:

            if not isinstance(argument, ast.Constant):
                continue

            value = argument.value

            if isinstance(value, str) and value.startswith("-"):

                flags.append({
                    "flag": value,
                    "line": node.lineno
                })

    return flags


def get_previous_file(repo_path, base_ref, file_path):
    """Retrieve a file's previous version from Git."""

    result = subprocess.run(
        ["git", "show", f"{base_ref}:{file_path}"],
        cwd=repo_path,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        return ""

    return result.stdout


def analyze_cli_changes(repo_path, base_ref="HEAD"):
    """Compare CLI flags before and after a code change."""

    repository = Path(repo_path)

    # Resolve the comparison base only once.
    base_ref = resolve_base_ref(repository, base_ref)

    changes = analyze_repository(repository, base_ref)

    results = []

    for file_change in changes["files"]:

        relative_path = file_change["file"]

        if not relative_path or not relative_path.endswith(".py"):
            continue

        old_source = get_previous_file(
            repository, base_ref, relative_path
        )

        current_file = repository / relative_path

        if current_file.is_file():
            new_source = current_file.read_text(encoding="utf-8")
        else:
            new_source = ""

        old_flags = extract_cli_flags(old_source)
        new_flags = extract_cli_flags(new_source)

        old_names = {item["flag"] for item in old_flags}
        new_names = {item["flag"] for item in new_flags}

        removed = [
            item for item in old_flags
            if item["flag"] not in new_names
        ]

        added = [
            item for item in new_flags
            if item["flag"] not in old_names
        ]

        if removed or added:

            results.append({
                "file": relative_path,
                "removed_flags": removed,
                "added_flags": added
            })

    return results


if __name__ == "__main__":

    import json

    repository = Path(__file__).resolve().parent.parent

    results = analyze_cli_changes(repository)

    print(json.dumps(results, indent=4))
