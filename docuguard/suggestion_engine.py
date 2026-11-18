from pathlib import Path

from .drift_detector import detect_documentation_drift
from .value_utils import replace_value_once


MIN_AUTOMATIC_SUGGESTION_CONFIDENCE = 0.85


def _evidence(finding, new_value):
    """Build consistent source references for a suggestion."""

    code_change = finding["code_change"]

    return {
        "symbol": finding["symbol"],
        "old_value": str(finding["old_value"]),
        "new_value": new_value,
        "code_file": code_change["file"],
        "code_line": (
            code_change.get("new_line")
            or code_change.get("old_line")
        ),
        "documentation_file": finding["documentation"]["file"],
        "documentation_line": finding["documentation"]["line"],
        "confidence": finding.get("confidence")
    }


def generate_suggestion(finding):
    """Generate a cautious correction from code and documentation evidence."""

    if finding["status"] != "likely_drift":
        return None

    old_value = str(finding["old_value"])
    new_value = finding["new_value"]
    sentence = finding["documentation"]["sentence"]

    # A removed flag without a replacement needs human judgement.
    if new_value == "<removed>":
        return {
            "status": "manual_review_required",
            "reason": (
                f"The code removed {old_value} without a detected "
                "replacement. The documentation may need rewriting."
            ),
            "evidence": _evidence(finding, None)
        }

    confidence = finding.get("confidence", 1.0)
    if confidence < MIN_AUTOMATIC_SUGGESTION_CONFIDENCE:
        return {
            "status": "manual_review_required",
            "reason": (
                f"The code-documentation relationship confidence is "
                f"{confidence:.2f}, below the automatic suggestion "
                f"threshold of {MIN_AUTOMATIC_SUGGESTION_CONFIDENCE:.2f}."
            ),
            "evidence": _evidence(finding, str(new_value))
        }

    suggested_sentence = replace_value_once(
        finding["old_value"], new_value, sentence
    )

    if suggested_sentence is None:
        return {
            "status": "manual_review_required",
            "reason": (
                "The old value does not occur exactly once as a complete "
                "value in the documentation sentence."
            ),
            "evidence": _evidence(finding, str(new_value))
        }

    return {
        "status": "suggestion_generated",
        "original_sentence": sentence,
        "suggested_sentence": suggested_sentence,
        "evidence": _evidence(finding, str(new_value)),
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
