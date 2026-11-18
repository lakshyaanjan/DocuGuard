import re
from pathlib import Path

from .relationship_engine import find_documentation_relationships
from .value_utils import contains_value


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


def find_historical_indicators(sentence):
    """Find historical phrases as whole words/phrases, not substrings."""

    indicators = []

    for indicator in sorted(HISTORICAL_INDICATORS):
        phrase = r"\s+".join(
            re.escape(part) for part in indicator.split()
        )
        pattern = re.compile(
            r"(?<!\w)" + phrase + r"(?!\w)",
            re.IGNORECASE
        )

        if pattern.search(sentence):
            indicators.append(indicator)

    return indicators


def evaluate_finding(finding):
    """Evaluate a documentation match without mutating the input finding."""

    result = dict(finding)
    sentence = finding["documentation"]["sentence"]

    old_value = str(finding["old_value"]).lower()
    new_value = finding["new_value"]

    historical_context = find_historical_indicators(sentence)

    # A removed flag has no replacement to compare against.
    if new_value == "<removed>":
        if historical_context:
            result["status"] = "needs_review"
            result["reason"] = (
                "The removed CLI flag appears in historical context. "
                "Manual review is needed."
            )
        else:
            result["status"] = "likely_drift"
            result["reason"] = (
                f"The CLI flag {old_value} was removed from the code, "
                "but the documentation still mentions it."
            )

    # Require the complete replacement value, not a substring.
    elif contains_value(new_value, sentence):
        result["status"] = "no_drift"
        result["reason"] = (
            "The documentation contains the replacement value. "
            "Manual review may be needed to understand the context."
        )

    elif historical_context:
        result["status"] = "needs_review"
        result["reason"] = (
            "The documentation contains language suggesting "
            "a historical reference to the old value."
        )

    else:
        result["status"] = "likely_drift"
        result["reason"] = (
            "The documentation contains the old value but not "
            "the new value, and no obvious historical indicator "
            "was detected."
        )

    result["historical_indicators"] = historical_context

    return result


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
