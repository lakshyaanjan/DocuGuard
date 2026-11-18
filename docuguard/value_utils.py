"""Exact matching helpers for documentation values."""

import re


def value_pattern(value):
    """Build a boundary-aware regular expression for a Python scalar value."""

    if isinstance(value, bool):
        rendered = "true" if value else "false"
        return re.compile(
            r"(?<![\w-])" + rendered
            + r"(?![\w-]|\.(?=[A-Za-z0-9]))",
            re.IGNORECASE
        )

    if isinstance(value, (int, float)):
        rendered = str(value)
        return re.compile(
            r"(?<![\w.+-])" + re.escape(rendered)
            + r"(?![\w-]|\.(?=\d))"
        )

    rendered = str(value)
    if not rendered:
        return re.compile(r"(?!x)x")

    escaped = re.escape(rendered)
    left_boundary = (
        r"(?<![\w.-])"
        if rendered[0].isalnum() or rendered[0] in "_-"
        else ""
    )
    right_boundary = (
        r"(?![\w-]|\.(?=[A-Za-z0-9]))"
        if rendered[-1].isalnum() or rendered[-1] in "_-"
        else ""
    )

    return re.compile(
        left_boundary + escaped + right_boundary,
        re.IGNORECASE
    )


def find_value_spans(value, text):
    """Return exact (start, end) matches for a scalar value in text."""

    return [match.span() for match in value_pattern(value).finditer(text)]


def contains_value(value, text):
    """Return whether a scalar value occurs as a complete value/token."""

    return bool(find_value_spans(value, text))


def replace_value_once(old_value, new_value, text):
    """Replace a value only when it appears exactly once as a complete token."""

    spans = find_value_spans(old_value, text)
    if len(spans) != 1:
        return None

    start, end = spans[0]
    return text[:start] + str(new_value) + text[end:]
