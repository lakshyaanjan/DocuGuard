import re
from pathlib import Path

from .relationship_engine import find_documentation_relationships
from .value_utils import contains_value


HISTORICAL_INDICATORS = {
    "formerly", "previously", "previous", "deprecated", "obsolete",
    "formerly used", "used to", "no longer", "before", "old value", "legacy"
}


def find_historical_indicators(sentence):
    """Find historical phrases as whole words/phrases, not substrings."""
    indicators = []
    for indicator in sorted(HISTORICAL_INDICATORS):
        phrase = r"\s+".join(re.escape(part) for part in indicator.split())
        pattern = re.compile(r"(?<!\w)" + phrase + r"(?!\w)", re.IGNORECASE)
        if pattern.search(sentence):
            indicators.append(indicator)
    return indicators


def evaluate_finding(finding):
    """Evaluate a documentation match without mutating the input finding."""
    result = dict(finding)
    sentence = finding["documentation"]["sentence"]
    old_value = str(finding.get("old_value", "")).lower()
    new_value = finding.get("new_value")
    historical_context = find_historical_indicators(sentence)
    drift_type = finding.get("drift_type")

    if drift_type == "configuration_option_added":
        result["status"] = "likely_drift"
        result["reason"] = (
            f"The code added configuration option {finding['option']!r} "
            "but the related documentation does not list it."
        )
    elif drift_type == "configuration_value_changed":
        if historical_context:
            result["status"] = "needs_review"
            result["reason"] = (
                "The documentation describes the previous configuration value "
                "in historical context. Manual review is needed."
            )
        elif contains_value(new_value, sentence):
            result["status"] = "no_drift"
            result["reason"] = "The documentation contains the updated configuration value."
        else:
            result["status"] = "likely_drift"
            result["reason"] = (
                f"The default for configuration option {finding['option']!r} "
                "changed, but the documentation still contains its old value."
            )
    elif drift_type == "configuration_option_removed":
        if historical_context:
            result["status"] = "needs_review"
            result["reason"] = (
                "The removed configuration option appears in historical "
                "context. Manual review is needed."
            )
        else:
            result["status"] = "likely_drift"
            result["reason"] = (
                f"The code removed configuration option {finding['option']!r}, "
                "but the documentation still lists it."
            )
    elif new_value == "<removed>":
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
            "The documentation contains the old value but not the new "
            "value, and no obvious historical indicator was detected."
        )

    result["historical_indicators"] = historical_context
    return result


def detect_documentation_drift(repo_path):
    """Find and evaluate potential documentation drift."""
    findings = find_documentation_relationships(repo_path)
    return [evaluate_finding(finding) for finding in findings]


if __name__ == "__main__":
    import json
    repository = Path(__file__).resolve().parent.parent
    print(json.dumps(detect_documentation_drift(repository), indent=4, ensure_ascii=False))
