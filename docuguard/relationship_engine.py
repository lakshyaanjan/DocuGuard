
import ast
import re
from pathlib import Path

from .git_analyzer import analyze_repository
from .content_extractor import extract_repository_content

GENERIC_IDENTIFIER_TERMS = {
    "default",
    "port",
    "value",
    "config",
    "configuration",
    "setting",
    "option",
    "name",
    "url",
    "host",
    "path",
    "timeout",
    "size"
}


def parse_assignment(line):
    """Extract a simple variable assignment from a changed line."""

    try:
        tree = ast.parse(line)
    except SyntaxError:
        return None

    if not tree.body or not isinstance(tree.body[0], ast.Assign):
        return None

    assignment = tree.body[0]

    if len(assignment.targets) != 1:
        return None

    target = assignment.targets[0]

    if not isinstance(target, ast.Name):
        return None

    try:
        value = ast.literal_eval(assignment.value)
    except (ValueError, TypeError):
        value = ast.unparse(assignment.value)

    return {
        "name": target.id,
        "value": value
    }


def split_identifier(name):
    """Convert identifiers into searchable words."""

    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    return set(re.findall(r"[a-zA-Z]+", name.lower()))


def value_in_sentence(value, sentence):
    """Check whether an old value appears in a documentation sentence."""

    value = str(value).strip()
    sentence = sentence.lower()

    if not value:
        return False

    if value.isdigit():
        return re.search(
            rf"(?<!\w){re.escape(value)}(?!\w)",
            sentence
        ) is not None

    return value.lower() in sentence


def find_documentation_relationships(repo_path):
    """Connect changed assignments to potentially outdated documentation."""

    repository = Path(repo_path)

    changes = analyze_repository(repository)
    documentation = extract_repository_content(repository)

    findings = []

    for file_change in changes["files"]:

        removed_assignments = []
        added_assignments = []

        for line in file_change["removed_lines"]:
            assignment = parse_assignment(line["content"])

            if assignment:
                removed_assignments.append({
                    **assignment,
                    "line": line["line"]
                })

        for line in file_change["added_lines"]:
            assignment = parse_assignment(line["content"])

            if assignment:
                added_assignments.append({
                    **assignment,
                    "line": line["line"]
                })

        for old in removed_assignments:

            for new in added_assignments:

                if old["name"] != new["name"]:
                    continue

                if old["value"] == new["value"]:
                    continue

                identifier_words = split_identifier(old["name"])

                for document in documentation:

                    sentence = document["content"]
                    sentence_words = set(
                        re.findall(r"[a-zA-Z]+", sentence.lower())
                    )

                    matched_terms = (
                        identifier_words & sentence_words
                    )

                    distinctive_terms = (
                        matched_terms - GENERIC_IDENTIFIER_TERMS
                    )

                    old_value_found = value_in_sentence(
                        old["value"], sentence
                    )

                    if not old_value_found or not distinctive_terms:
                        continue

                    confidence = (
                        0.95
                        if matched_terms == identifier_words
                        else 0.75
                    )

                    findings.append({
                        "type": "potential_documentation_drift",
                        "symbol": old["name"],
                        "old_value": old["value"],
                        "new_value": new["value"],
                        "code_change": {
                            "file": file_change["file"],
                            "old_line": old["line"],
                            "new_line": new["line"]
                        },
                        "documentation": {
                            "file": document["file"],
                            "line": document["line"],
                            "sentence": sentence
                        },
                        "matched_terms": sorted(matched_terms),
                        "confidence": confidence,
                        "reason": (
                            "The documentation contains the old value "
                            "and terminology related to the changed "
                            "code identifier."
                        )
                    })

    return findings


if __name__ == "__main__":

    import json

    repository = Path(__file__).resolve().parent.parent

    results = find_documentation_relationships(repository)

    print(json.dumps(results, indent=4, ensure_ascii=False))
