"""Resolve local, GitHub and ZIP sources into temporary/local directories."""

from __future__ import annotations

import base64
import os
import re
import subprocess
import tempfile
from contextlib import ExitStack
from pathlib import Path
from urllib.parse import urlparse

from .zip_utils import safe_extract_zip


class SourceError(ValueError):
    """Raised when a source cannot be resolved safely."""


def validate_github_url(url: str) -> str:
    """Allow only a normal HTTPS github.com owner/repository URL."""
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise SourceError("Only HTTPS GitHub repository URLs are supported.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SourceError("GitHub URLs must not contain credentials, query strings or fragments.")
    path = parsed.path.strip("/")
    parts = path.split("/")
    if len(parts) != 2 or not all(parts):
        raise SourceError("Expected a repository URL like https://github.com/owner/repository.")
    repository = parts[1][:-4] if parts[1].endswith(".git") else parts[1]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", parts[0]) or not re.fullmatch(r"[A-Za-z0-9_.-]+", repository):
        raise SourceError("The GitHub owner or repository name contains unsupported characters.")
    return f"https://github.com/{parts[0]}/{repository}.git"


def clone_github_repository(url: str, destination: Path, branch: str | None = None) -> tuple[str, str | None]:
    """Clone a public GitHub repository, or a private one using an env token.

    Two commits are fetched so the UI can compare HEAD with HEAD~1. The token
    is passed to Git through environment-based config and never stored.
    """
    clone_url = validate_github_url(url)
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    token = env.get("DOCUGUARD_GITHUB_TOKEN")
    if token:
        encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        config_count = int(env.get("GIT_CONFIG_COUNT", "0"))
        env["GIT_CONFIG_COUNT"] = str(config_count + 1)
        env[f"GIT_CONFIG_KEY_{config_count}"] = "http.https://github.com/.extraheader"
        env[f"GIT_CONFIG_VALUE_{config_count}"] = f"AUTHORIZATION: basic {encoded}"

    command = ["git", "clone", "--depth", "2"]
    if branch:
        command.extend(["--branch", branch])
    command.extend([clone_url, str(destination)])
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, env=env,
            timeout=240, check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise SourceError("GitHub clone timed out after 240 seconds.") from error
    if result.returncode != 0:
        message = result.stderr.strip().splitlines()
        detail = message[-1] if message else "Git clone failed."
        raise SourceError(f"Could not clone GitHub repository: {detail[:400]}")
    return clone_url.removesuffix(".git"), branch


def archive_root(extracted: Path) -> Path:
    """Use the only top-level directory as root when a ZIP wraps one folder."""
    entries = list(extracted.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return extracted


def resolve_source(
    stack: ExitStack,
    *,
    local_path: str | Path | None = None,
    github_url: str | None = None,
    zip_path: str | Path | None = None,
    website_url: str | None = None,
    branch: str | None = None,
    label: str = "source",
) -> tuple[Path, str | None]:
    """Resolve exactly one source selector; temporary sources live in ExitStack."""
    selectors = sum(value is not None for value in (local_path, github_url, zip_path, website_url))
    if selectors != 1:
        raise SourceError(f"Provide exactly one source selector for {label}.")

    if local_path is not None:
        path = Path(local_path).expanduser().resolve()
        if not path.exists() or not path.is_dir():
            raise SourceError(f"{label.capitalize()} path does not exist or is not a directory: {path}")
        return path, None

    temporary = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix=f"docuguard-{label}-")))
    if github_url is not None:
        repository_origin, _ = clone_github_repository(github_url, temporary / "checkout", branch)
        return temporary / "checkout", repository_origin

    if website_url is not None:
        if label != "docs":
            raise SourceError("Website crawling is supported only for documentation sources.")
        from .website import crawl_documentation_website
        website_root = temporary / "website"
        crawl_documentation_website(website_url, website_root)
        return website_root, website_url.strip()

    archive = Path(zip_path).expanduser().resolve()
    if not archive.is_file() or archive.suffix.lower() != ".zip":
        raise SourceError(f"{label.capitalize()} ZIP must be an existing .zip file.")
    extracted = temporary / "extracted"
    safe_extract_zip(archive, extracted)
    return archive_root(extracted), None
