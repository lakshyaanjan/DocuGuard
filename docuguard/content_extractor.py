
import re
from pathlib import Path

from .document_crawler import crawl_repository


def extract_sentences(document):
    """Extract individual sentences while preserving source locations."""

    extracted = []

    for entry in document["lines"]:

        line_number = entry["line"]
        content = entry["content"].strip()

        if not content:
            continue

        # Skip Markdown headings
        if content.startswith("#"):
            continue

        # Skip fenced code block markers and their contents
        if content.startswith("```") or content.startswith("~~~"):
            continue

        # Split ordinary prose into sentences
        sentences = re.split(r'(?<=[.!?])\s+', content)

        for sentence in sentences:

            sentence = sentence.strip()

            if not sentence:
                continue

            extracted.append({
                "type": "sentence",
                "content": sentence,
                "file": document["file"],
                "line": line_number
            })

    return extracted


def extract_repository_content(repo_path):
    """Extract documentation sentences from the repository."""

    documents = crawl_repository(repo_path)

    all_content = []

    for document in documents:

        if "error" in document:
            continue

        all_content.extend(extract_sentences(document))

    return all_content


if __name__ == "__main__":

    import json

    repository = Path(__file__).resolve().parent.parent

    content = extract_repository_content(repository)

    print(json.dumps(content, indent=4, ensure_ascii=False))
