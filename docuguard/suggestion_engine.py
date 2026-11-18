
from pathlib import Path

from .drift_detector import detect_documentation_drift


def generate_suggestion(finding):
    """Generate a documentation correction from verified code evidence."""

    if finding["status"] != "likely_drift":
        return None

    old_value = str(finding["old_value"])
    new_value = str(finding["new_value"])

    sentence = finding["documentation"]["sentence"]

    # Replace the old value only when it occurs exactly once.
    if sentence.count(old_value) != 1:
        return {
            "status": "manual_review_required",
            "reason": "The old value does not occur exactly once."
        }

    suggested_sentence = sentence.replace(old_value, new_value, 1)

    return {
        "status": "suggestion_generated",
        "original_sentence": sentence,
        "suggested_sentence": suggested_sentence,
        "evidence": {
            "symbol": finding["symbol"],
            "old_value": finding["old_value"],
            "new_value": finding["new_value"],
            "code_file": finding["code_change"]["file"],
            "code_line": finding["code_change"]["new_line"],
            "documentation_file": finding["documentation"]["file"],
            "documentation_line": finding["documentation"]["line"]
        },
        "explanation": (
            f"The code changed {finding['symbol']} "
            f"from {old_value} to {new_value}. "
            "The documentation still contains the old value."
        )
    }


def generate_all_suggestions(repo_path):
    """Generate suggestions for all likely documentation drift findings."""

    findings = detect_documentation_drift(repo_path)

    suggestions = []

    for finding in findings:

        suggestion = generate_suggestion(finding)

        if suggestion is not None:
            suggestions.append(suggestion)

    return suggestions


if __name__ == "__main__":

    import json

    repository = Path(__file__).resolve().parent.parent

    results = generate_all_suggestions(repository)

    print(json.dumps(results, indent=4, ensure_ascii=False))
