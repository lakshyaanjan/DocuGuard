import ast
import re
from pathlib import Path

from .git_analyzer import analyze_repository
from .content_extractor import extract_repository_content
from .cli_analyzer import analyze_cli_changes
from .value_utils import contains_value


GENERIC_IDENTIFIER_TERMS = {
    "default", "port", "value", "config", "configuration",
    "setting", "option", "name", "url", "host", "path",
    "timeout", "size"
}
CONCEPT_TERMS = {
    "application": {"service", "app", "program"},
    "port": {"listener", "listening"},
    "timeout": {"wait", "duration"},
    "host": {"hostname", "server"},
    "url": {"endpoint", "address"},
    "path": {"directory", "location"},
    "size": {"limit", "capacity"},
    "default": {"initial", "initially"},
}
KNOWN_ENTITY_ALIASES = {"app": "application"}


def parse_assignment(line):
    """Extract a simple variable assignment from a changed line."""
    try:
        tree = ast.parse(line)
    except SyntaxError:
        return None
    if not tree.body or not isinstance(tree.body[0], ast.Assign):
        return None
    assignment = tree.body[0]
    if len(assignment.targets) != 1 or not isinstance(assignment.targets[0], ast.Name):
        return None
    try:
        value = ast.literal_eval(assignment.value)
    except (ValueError, TypeError):
        value = ast.unparse(assignment.value)
    return {"name": assignment.targets[0].id, "value": value}


def split_identifier(name):
    """Convert identifiers into searchable words."""
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    return set(re.findall(r"[a-zA-Z]+", name.lower()))


def expand_identifier_concepts(identifier_words):
    """Add known prose terms related to identifier concepts."""
    expanded_words = set(identifier_words)
    for word in identifier_words:
        expanded_words.update(CONCEPT_TERMS.get(word, set()))
    return expanded_words


def has_conflicting_entity_label(sentence, identifier_words):
    """Avoid matching a passage explicitly naming a different entity."""
    labels = re.findall(
        r"\b([A-Z]{2,})\s+(?:service|server|application|program)\b",
        sentence
    )
    expanded_identifier_words = expand_identifier_concepts(identifier_words)
    return any(
        KNOWN_ENTITY_ALIASES.get(label.lower(), label.lower())
        not in expanded_identifier_words
        for label in labels
    )


def find_dictionary_option_relationships(old, new, file_change, documentation):
    """Find dictionary keys added/removed without a matching documentation entry.

    Supports literal dictionaries assigned on one changed Python line. A
    relationship is only considered when docs already describe at least one
    old key and its value in the same passage.
    """
    if not isinstance(old["value"], dict) or not isinstance(new["value"], dict):
        return []

    old_options = old["value"]
    new_options = new["value"]
    added_options = {key: value for key, value in new_options.items() if key not in old_options}
    removed_options = {key: value for key, value in old_options.items() if key not in new_options}
    changed_options = {
        key for key in old_options.keys() & new_options.keys()
        if old_options[key] != new_options[key]
    }
    if not added_options and not removed_options and not changed_options:
        return []

    docs_by_file = {}
    for item in documentation:
        docs_by_file.setdefault(item["file"], []).append(item)

    findings = []
    for doc_file, passages in docs_by_file.items():
        evidence_passages = [
            passage for passage in passages
            if any(
                contains_value(key, passage["content"])
                and contains_value(value, passage["content"])
                for key, value in old_options.items()
            )
        ]
        if not evidence_passages:
            continue

        for option in old_options.keys() & new_options.keys():
            old_default = old_options[option]
            new_default = new_options[option]
            if old_default == new_default:
                continue
            matches = [
                passage for passage in passages
                if contains_value(option, passage["content"])
                and contains_value(old_default, passage["content"])
            ]
            if not matches:
                continue
            evidence = matches[0]
            findings.append({
                "type": "potential_documentation_drift",
                "drift_type": "configuration_value_changed",
                "symbol": f"{old['name']}.{option}",
                "old_value": old_default,
                "new_value": new_default,
                "option": option,
                "option_default": new_default,
                "code_change": {
                    "file": file_change["file"],
                    "old_line": old["line"],
                    "new_line": new["line"]
                },
                "documentation": {
                    "file": doc_file,
                    "line": evidence["line"],
                    "sentence": evidence["content"]
                },
                "matched_terms": [str(option)],
                "confidence": 0.92,
                "reason": (
                    f"The default for configuration option {option!r} "
                    "changed, but the documentation still contains its old value."
                )
            })

        for option, default in added_options.items():
            if any(contains_value(option, item["content"]) for item in passages):
                continue
            evidence = evidence_passages[0]
            findings.append({
                "type": "potential_documentation_drift",
                "drift_type": "configuration_option_added",
                "symbol": old["name"],
                "old_value": None,
                "new_value": option,
                "option": option,
                "option_default": default,
                "code_change": {
                    "file": file_change["file"],
                    "old_line": old["line"],
                    "new_line": new["line"]
                },
                "documentation": {
                    "file": doc_file,
                    "line": evidence["line"],
                    "sentence": evidence["content"]
                },
                "matched_terms": [str(key) for key in old_options],
                "confidence": 0.82,
                "reason": (
                    f"The code added configuration option {option!r}, "
                    f"but the related documentation in {doc_file} does not list it."
                )
            })

        for option, old_default in removed_options.items():
            matches = [
                passage for passage in passages
                if contains_value(option, passage["content"])
                and contains_value(old_default, passage["content"])
            ]
            if not matches:
                continue
            evidence = matches[0]
            findings.append({
                "type": "potential_documentation_drift",
                "drift_type": "configuration_option_removed",
                "symbol": old["name"],
                "old_value": option,
                "new_value": "<removed>",
                "option": option,
                "option_default": old_default,
                "code_change": {
                    "file": file_change["file"],
                    "old_line": old["line"],
                    "new_line": new["line"]
                },
                "documentation": {
                    "file": doc_file,
                    "line": evidence["line"],
                    "sentence": evidence["content"]
                },
                "matched_terms": [str(option)],
                "confidence": 0.90,
                "reason": (
                    f"The code removed configuration option {option!r}, "
                    "but the documentation still lists its old value."
                )
            })
    return findings


def find_assignment_documentation_relationships(repo_path, docs_path=None):
    """Connect changed assignments to potentially outdated documentation."""
    repository = Path(repo_path)
    changes = analyze_repository(repository)
    documentation = extract_repository_content(docs_path or repository)
    findings = []

    for file_change in changes["files"]:
        removed_assignments = []
        added_assignments = []
        for line in file_change["removed_lines"]:
            assignment = parse_assignment(line["content"])
            if assignment:
                removed_assignments.append({**assignment, "line": line["line"]})
        for line in file_change["added_lines"]:
            assignment = parse_assignment(line["content"])
            if assignment:
                added_assignments.append({**assignment, "line": line["line"]})

        for old in removed_assignments:
            for new in added_assignments:
                if old["name"] != new["name"] or old["value"] == new["value"]:
                    continue
                if isinstance(old["value"], dict) and isinstance(new["value"], dict):
                    findings.extend(
                        find_dictionary_option_relationships(
                            old, new, file_change, documentation
                        )
                    )
                    continue

                identifier_words = split_identifier(old["name"])
                expanded_identifier_words = expand_identifier_concepts(identifier_words)
                for document in documentation:
                    sentence = document["content"]
                    if has_conflicting_entity_label(sentence, identifier_words):
                        continue
                    sentence_words = set(re.findall(r"[a-zA-Z]+", sentence.lower()))
                    matched_terms = expanded_identifier_words & sentence_words
                    distinctive_terms = matched_terms - GENERIC_IDENTIFIER_TERMS
                    old_value_found = contains_value(old["value"], sentence)
                    if not old_value_found or not distinctive_terms:
                        continue
                    confidence = (
                        0.95 if identifier_words.issubset(sentence_words) else 0.75
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
                            "The documentation contains the old value and "
                            "terminology related to the changed code identifier."
                        )
                    })
    return findings


def find_cli_documentation_relationships(repo_path, docs_path=None):
    """Find documentation passages that mention removed CLI flags."""
    repository = Path(repo_path)
    cli_changes = analyze_cli_changes(repository)
    documentation = extract_repository_content(docs_path or repository)
    findings = []

    for change in cli_changes:
        removed_flags = change["removed_flags"]
        added_flags = change["added_flags"]
        replacement = added_flags[0]["flag"] if len(added_flags) == 1 else None
        for removed in removed_flags:
            old_flag = removed["flag"]
            for document in documentation:
                sentence = document["content"]
                if not contains_value(old_flag, sentence):
                    continue
                findings.append({
                    "type": "potential_documentation_drift",
                    "symbol": old_flag,
                    "old_value": old_flag,
                    "new_value": replacement or "<removed>",
                    "code_change": {
                        "file": change["file"],
                        "old_line": removed["line"],
                        "new_line": added_flags[0]["line"] if replacement else None
                    },
                    "documentation": {
                        "file": document["file"],
                        "line": document["line"],
                        "sentence": sentence
                    },
                    "matched_terms": [old_flag],
                    "confidence": 0.99,
                    "reason": (
                        f"The code removed CLI flag {old_flag}, "
                        "but the documentation still mentions it."
                    )
                })
    return findings


def find_documentation_relationships(repo_path, docs_path=None):
    """Combine assignment-based and CLI-based documentation detection."""
    return (
        find_assignment_documentation_relationships(repo_path, docs_path)
        + find_cli_documentation_relationships(repo_path, docs_path)
    )


if __name__ == "__main__":
    import json
    repository = Path(__file__).resolve().parent.parent
    print(json.dumps(find_documentation_relationships(repository), indent=4, ensure_ascii=False))
