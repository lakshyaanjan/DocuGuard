"""Small deterministic helpers for ingestion."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def stable_id(*parts: str, length: int = 24) -> str:
    joined = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8", errors="replace")).hexdigest()[:length]


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "project"


def git_metadata(root: Path) -> tuple[str | None, str | None]:
    """Return (HEAD commit, branch) without failing for ZIP/non-Git sources."""
    root = Path(root)
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"], cwd=root,
            capture_output=True, text=True, timeout=8, check=False,
        )
        branch = subprocess.run(
            ["git", "symbolic-ref", "--short", "-q", "HEAD"], cwd=root,
            capture_output=True, text=True, timeout=8, check=False,
        )
        commit_sha = commit.stdout.strip() if commit.returncode == 0 else None
        branch_name = branch.stdout.strip() if branch.returncode == 0 else None
        return commit_sha, branch_name
    except (OSError, subprocess.TimeoutExpired):
        return None, None


def json_line(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
