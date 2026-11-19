"""File selection and size limits for safe repository ingestion."""

from __future__ import annotations

import re
from pathlib import Path

DOCUMENTATION_EXTENSIONS = {
    ".md", ".markdown", ".mdown", ".rst", ".txt", ".adoc", ".asciidoc",
    ".html", ".htm", ".xhtml",
}

SOURCE_LANGUAGES = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".jsx": "jsx", ".ts": "typescript", ".tsx": "tsx",
    ".mjs": "javascript", ".cjs": "javascript",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp", ".hh": "cpp",
    ".java": "java", ".go": "go", ".rs": "rust", ".rb": "ruby", ".php": "php",
    ".cs": "csharp", ".swift": "swift", ".kt": "kotlin", ".kts": "kotlin",
    ".scala": "scala", ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".sql": "sql", ".vue": "vue", ".svelte": "svelte",
}

CONFIG_EXTENSIONS = {
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
    ".ini": "ini", ".cfg": "ini", ".properties": "properties", ".xml": "xml",
}

SPECIAL_SOURCE_NAMES = {"dockerfile": "dockerfile", "makefile": "makefile", "justfile": "makefile"}

IGNORED_DIRECTORIES = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "__pycache__",
    "node_modules", "vendor", "dist", "build", "target", ".next", ".nuxt",
    ".idea", ".vscode", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".tox", "coverage", "htmlcov", ".docuguard",
}

SENSITIVE_NAMES = {
    ".env", ".env.local", ".env.production", "id_rsa", "id_ed25519",
    "credentials.json", "secrets.json", "service-account.json",
}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".keystore", ".jks"}

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024
MAX_FILES = 20_000
MAX_CHUNK_CHARS = 8_000
MAX_TEXT_LINES = 400


def classify_file(path: Path) -> tuple[str | None, str | None]:
    """Return (file_kind, language) for supported textual inputs."""
    name = path.name.lower()
    suffix = path.suffix.lower()
    if name in SPECIAL_SOURCE_NAMES:
        return "source", SPECIAL_SOURCE_NAMES[name]
    if suffix in DOCUMENTATION_EXTENSIONS:
        return "documentation", None
    if suffix in SOURCE_LANGUAGES:
        return "source", SOURCE_LANGUAGES[suffix]
    if suffix in CONFIG_EXTENSIONS:
        return "configuration", CONFIG_EXTENSIONS[suffix]
    return None, None


def should_skip_path(path: Path) -> str | None:
    """Return a reason for skipping a path, or None when it is eligible."""
    if any(part.lower() in IGNORED_DIRECTORIES for part in path.parts):
        return "ignored_directory"
    name = path.name.lower()
    if name in SENSITIVE_NAMES or name.startswith(".env."):
        return "sensitive_file_name"
    if path.suffix.lower() in SENSITIVE_SUFFIXES:
        return "sensitive_file_type"
    if path.is_symlink():
        return "symlink"
    if not path.is_file():
        return "not_regular_file"
    return None

_PROBABLE_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|secret[_-]?access[_-]?key|password)\b\s*[:=]\s*['\"]?[A-Za-z0-9/+=_-]{24,}"),
]


def contains_probable_secret(text: str) -> bool:
    """Conservatively reject files containing common literal credential forms."""
    return any(pattern.search(text) for pattern in _PROBABLE_SECRET_PATTERNS)
