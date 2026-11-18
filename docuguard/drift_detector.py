
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

    historical_context = [
        indicator
        for indicator in HISTORICAL_INDICATORS
        if indicator in sentence
    ]

    # A removed flag has no replacement to compare against.
    if new_value == "<removed>":
        if historical_context:
            finding["status"] = "needs_review"
            finding["reason"] = (
                "The removed CLI flag appears in historical context. "
                "Manual review is needed."
            )
        else:
            finding["status"] = "likely_drift"
            finding["reason"] = (
                f"The CLI flag {old_value} was removed from the code, "
                "but the documentation still mentions it."
            )

    # A replacement exists.
    elif new_value in sentence:
        finding["status"] = "no_drift"
        finding["reason"] = (
            "The documentation contains the replacement value. "
            "Manual review may be needed to understand the context."
        )

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
