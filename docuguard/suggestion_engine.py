from pathlib import Path

from .drift_detector import detect_documentation_drift
from .value_utils import replace_value_once


MIN_AUTOMATIC_SUGGESTION_CONFIDENCE = 0.85


def _evidence(finding, new_value):
    """Build consistent source references for a suggestion."""
    code_change = finding["code_change"]
    evidence = {
        "symbol": finding["symbol"],
        "old_value": str(finding.get("old_value")),
        "new_value": new_value,
        "code_file": code_change["file"],
        "code_line": code_change.get("new_line") or code_change.get("old_line"),
        "documentation_file": finding["documentation"]["file"],
        "documentation_line": finding["documentation"]["line"],
        "confidence": finding.get("confidence")
    }
    if finding.get("option") is not None:
        evidence["option"] = finding["option"]
        evidence["option_default"] = finding.get("option_default")
    return evidence


def generate_suggestion(finding):
    """Generate a cautious correction from code and documentation evidence."""
    if finding["status"] != "likely_drift":
        return None

    old_value = str(finding.get("old_value"))
    new_value = finding.get("new_value")
    sentence = finding["documentation"]["sentence"]
    drift_type = finding.get("drift_type")

    if drift_type in {"configuration_option_added", "configuration_option_removed"}:
        action = (
            "Add this option to the related configuration documentation."
            if drift_type == "configuration_option_added"
            else "Remove or clearly mark this option as removed in the documentation."
        )
        return {
            "status": "manual_review_required",
            "reason": (
                f"{action} The expected option is {finding['option']!r}; "
                f"its code default is {finding.get('option_default')!r}. "
                "DocuGuard does not assume the table's column format."
            ),
            "evidence": _evidence(finding, str(new_value))
        }

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
            f"The code changed {finding['symbol']} from {old_value} "
            f"to {new_value}. The documentation still contains the old value."
        )
    }


def generate_all_suggestions(repo_path, docs_path=None):
    """Generate suggestions for all likely documentation drift findings."""
    findings = detect_documentation_drift(repo_path, docs_path)
    suggestions = []
    for finding in findings:
        suggestion = generate_suggestion(finding)
        if suggestion is not None:
            suggestions.append(suggestion)
    return suggestions


if __name__ == "__main__":
    import json
    repository = Path(__file__).resolve().parent.parent
    print(json.dumps(generate_all_suggestions(repository), indent=4, ensure_ascii=False))
