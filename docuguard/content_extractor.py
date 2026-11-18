import re
from pathlib import Path

from .document_crawler import crawl_repository


def extract_sentences(document):
    """Extract prose and Markdown table rows while preserving source locations."""
    extracted = []
    inside_fence = False
    fence_marker = None

    for entry in document["lines"]:
        line_number = entry["line"]
        content = entry["content"].strip()
        if not content:
            continue

        fence_match = re.match(r"^(" + chr(96) + r"{3,}|~{3,})", content)
        if fence_match:
            marker = fence_match.group(1)[0]
            if not inside_fence:
                inside_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                inside_fence = False
                fence_marker = None
            continue

        if inside_fence or content.startswith("#"):
            continue

        if content.startswith("|") and content.endswith("|"):
            if re.fullmatch(r"\|[\s:|-]+\|", content):
                continue
            extracted.append({
                "type": "table_row",
                "content": content,
                "file": document["file"],
                "line": line_number
            })
            continue

        sentences = re.split(r'(?<=[.!?])\s+', content)
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence:
                extracted.append({
                    "type": "sentence",
                    "content": sentence,
                    "file": document["file"],
                    "line": line_number
                })
    return extracted


def extract_repository_content(repo_path):
    """Extract documentation sentences and table rows from the repository."""
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
    print(json.dumps(extract_repository_content(repository), indent=4, ensure_ascii=False))
