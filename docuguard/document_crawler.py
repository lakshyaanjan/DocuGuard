
from pathlib import Path


DOCUMENTATION_EXTENSIONS = {
    ".md",
    ".markdown",
    ".rst",
    ".html",
    ".htm"
}

IGNORED_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules"
}


def discover_documents(repo_path):
    """Find documentation files inside a repository."""

    repository = Path(repo_path).resolve()
    documents = []

    for file_path in repository.rglob("*"):

        if not file_path.is_file():
            continue

        relative_path = file_path.relative_to(repository)

        if any(
            part in IGNORED_DIRECTORIES
            for part in relative_path.parts
        ):
            continue

        if file_path.suffix.lower() in DOCUMENTATION_EXTENSIONS:
            documents.append(file_path)

    return documents


def read_document(file_path, repo_path):
    """Read a document and preserve relative paths and line numbers."""

    path = Path(file_path)
    repository = Path(repo_path).resolve()

    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {
            "file": str(path.relative_to(repository)),
            "error": "Unable to decode file as UTF-8",
            "lines": []
        }

    return {
        "file": str(path.relative_to(repository)).replace("\\", "/"),
        "lines": [
            {
                "line": number,
                "content": line
            }
            for number, line in enumerate(content.splitlines(), start=1)
        ]
    }


def crawl_repository(repo_path):
    """Discover and read all supported documentation files."""

    repository = Path(repo_path).resolve()
    documents = discover_documents(repository)

    return [
        read_document(file_path, repository)
        for file_path in documents
    ]


if __name__ == "__main__":

    import json

    repository = Path(__file__).resolve().parent.parent

    results = crawl_repository(repository)

    print(json.dumps(results, indent=4, ensure_ascii=False))
