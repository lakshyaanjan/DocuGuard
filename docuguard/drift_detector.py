
from pathlib import Path

from .relationship_engine import find_documentation_relationships


HISTORICAL_INDICATORS = {
    "formerly",
    "previously",
    "previous",
    "deprecated",
    "obsolete",
    "formerly used",
    "used to",
    "no longer",
    "before",
    "old value",
    "legacy"
}


def evaluate_finding(finding):
    """Evaluate whether a documentation match looks like actual drift."""

    sentence = finding["documentation"]["sentence"].lower()

    old_value = str(finding["old_value"]).lower()
    new_value = str(finding["new_value"]).lower()

    # Check whether the sentence explicitly describes historical information.
    historical_context = [
        indicator
        for indicator in HISTORICAL_INDICATORS
        if indicator in sentence
    ]

    # Check whether the documentation contains the new value.
    new_value_present = new_value in sentence

    # If the new value is present, the documentation may already be updated.
    if new_value_present:
        finding["status"] = "no_drift"
        finding["reason"] = (
            "The documentation also contains the new value. "
            "Manual review may be needed to understand the context."
        )

    # Historical references should not automatically be flagged.
    elif historical_context:
        finding["status"] = "needs_review"
        finding["reason"] = (
            "The documentation contains language suggesting "
            "a historical reference to the old value."
        )

    else:
        finding["status"] = "likely_drift"
        finding["reason"] = (
            "The documentation contains the old value but not "
            "the new value, and no obvious historical indicator "
            "was detected."
        )

    finding["historical_indicators"] = historical_context

    return finding


def detect_documentation_drift(repo_path):
    """Find and evaluate potential documentation drift."""

    findings = find_documentation_relationships(repo_path)

    evaluated_findings = [
        evaluate_finding(finding)
        for finding in findings
    ]

    return evaluated_findings


if __name__ == "__main__":

    import json

    repository = Path(__file__).resolve().parent.parent

    results = detect_documentation_drift(repository)

    print(json.dumps(results, indent=4, ensure_ascii=False))
