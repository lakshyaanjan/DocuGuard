"""Build a versioned, traceable local data snapshot for future RAG retrieval."""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .extractors import extract_file_chunks
from .models import Chunk, FileRecord, FileSummary, IngestionResult, SourceRecord
from .policy import (
    MAX_CHUNK_CHARS, MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES,
    classify_file, contains_probable_secret, should_skip_path,
)
from .utils import git_metadata, json_line, sha256_text, slugify, stable_id


class IngestionError(RuntimeError):
    """Raised when a source cannot be ingested consistently."""


def _iter_files(root: Path):
    """Walk without following symlinks or entering generated/dependency dirs."""
    from .policy import IGNORED_DIRECTORIES

    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        dirs[:] = [
            name for name in dirs
            if name.lower() not in IGNORED_DIRECTORIES
            and not (current_path / name).is_symlink()
        ]
        for name in files:
            yield current_path / name


def _read_text(path: Path) -> tuple[str | None, str | None]:
    try:
        # tokenize.open honours PEP 263 encoding declarations in Python files.
        if path.suffix.lower() in {".py", ".pyi"}:
            import tokenize
            with tokenize.open(path) as handle:
                return handle.read(), None
        return path.read_text(encoding="utf-8-sig"), None
    except UnicodeDecodeError:
        return None, "not valid UTF-8 text"
    except (OSError, SyntaxError) as error:
        return None, f"could not read file: {error}"


def _relative_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _file_candidates(root: Path, *, allow_docs: bool, allow_code: bool):
    for path in _iter_files(root):
        reason = should_skip_path(path)
        if reason:
            continue
        kind, language = classify_file(path)
        if kind == "documentation" and not allow_docs:
            continue
        if kind in {"source", "configuration"} and not allow_code:
            continue
        if kind:
            yield path, kind, language


def _chunk_id(project_id: str, source_id: str, path: str, raw: dict[str, Any], commit: str | None) -> str:
    return stable_id(
        project_id, source_id, path, raw["kind"], str(raw["start_line"]),
        str(raw["end_line"]), raw["content"], commit or "working-tree",
    )


def _build_file_summary(
    project_id: str, source_id: str, path: str, chunks: list[Chunk],
    *, summary_scope: str = "file", section: str | None = None,
) -> FileSummary:
    selected = chunks[:8]
    lines: list[str] = []
    for chunk in selected:
        if chunk.kind == "documentation_heading":
            lines.append(f"Section: {chunk.content[:180]}")
        elif chunk.kind in {"python_function", "python_class", "python_assignment"}:
            label = chunk.symbol or chunk.kind
            lines.append(f"{chunk.kind.replace('_', ' ').title()}: {label}")
        elif chunk.kind in {"python_docstring", "documentation_paragraph", "documentation_list_item", "documentation_table_row", "python_comment", "source_comment"}:
            snippet = " ".join(chunk.content.split())
            lines.append(snippet[:220])
    # Keep summaries explicitly extractive; later LLM summaries can replace or
    # augment these while preserving their source_chunk_ids.
    summary = "\n".join(dict.fromkeys(lines))
    if not summary:
        summary = f"{len(chunks)} indexed chunk(s) extracted from {path}."
    return FileSummary(
        summary_id=stable_id(project_id, source_id, path, summary_scope, section or "", "extractive-summary-v1"),
        project_id=project_id,
        source_id=source_id,
        path=path,
        summary_method="extractive_v1",
        summary_text=summary,
        source_chunk_ids=[chunk.chunk_id for chunk in selected],
        chunk_count=len(chunks),
        summary_scope=summary_scope,
        section=section,
    )


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    content = "".join(json_line(record) + "\n" for record in records)
    _atomic_write_text(path, content)


def _split_content_with_lines(content: str, max_chars: int = MAX_CHUNK_CHARS) -> list[tuple[str, int, int]]:
    """Split an oversized extracted chunk while retaining relative line offsets."""
    lines = content.splitlines()
    if not lines:
        return []
    parts: list[tuple[str, int, int]] = []
    current: list[str] = []
    current_start = 0
    current_size = 0

    def flush() -> None:
        nonlocal current, current_size
        if current:
            parts.append(("\n".join(current), current_start, current_start + len(current) - 1))
            current = []
            current_size = 0

    for index, line in enumerate(lines):
        if len(line) > max_chars:
            flush()
            for offset in range(0, len(line), max_chars):
                fragment = line[offset:offset + max_chars]
                if fragment.strip():
                    parts.append((fragment, index, index))
            continue
        if current and current_size + len(line) + 1 > max_chars:
            flush()
        if not current:
            current_start = index
        current.append(line)
        current_size += len(line) + 1
    flush()
    return parts


def ingest_project(
    *,
    repo_path: str | Path,
    docs_path: str | Path | None = None,
    project_name: str | None = None,
    output_dir: str | Path | None = None,
    code_origin: str | None = None,
    docs_origin: str | None = None,
    max_file_bytes: int = MAX_FILE_BYTES,
    max_total_bytes: int = MAX_TOTAL_BYTES,
    max_files: int = MAX_FILES,
) -> IngestionResult:
    """Extract a complete local snapshot of code, docs and their evidence.

    `repo_path` must be a checked-out repository or extracted source directory.
    `docs_path` may point to another checkout/directory. If omitted, docs and
    code are discovered in the same root. The output is a versioned snapshot
    containing manifest.json, files.jsonl, chunks.jsonl, summaries.jsonl and
    project_summary.json.
    """
    code_root = Path(repo_path).expanduser().resolve()
    docs_root = Path(docs_path).expanduser().resolve() if docs_path else code_root
    if not code_root.is_dir():
        raise IngestionError(f"Code repository path is not a directory: {code_root}")
    if not docs_root.is_dir():
        raise IngestionError(f"Documentation path is not a directory: {docs_root}")
    same_root = code_root == docs_root
    if max_file_bytes < 1 or max_total_bytes < 1 or max_files < 1:
        raise IngestionError("Ingestion limits must all be positive integers.")

    code_commit, code_branch = git_metadata(code_root)
    docs_commit, docs_branch = (code_commit, code_branch) if same_root else git_metadata(docs_root)
    project_name = (project_name or code_root.name or "DocuGuard Project").strip()
    project_id = f"{slugify(project_name)}-{stable_id(project_name, code_commit or code_root.name, docs_commit or docs_root.name, length=10)}"

    sources: list[SourceRecord] = [SourceRecord(
        source_id="code", source_type="code_repository", display_name=code_root.name,
        root_label="code_repository", origin=code_origin,
        commit_sha=code_commit, branch=code_branch,
    )]
    if same_root:
        sources.append(SourceRecord(
            source_id="docs", source_type="documentation_source",
            display_name=f"Documentation in {code_root.name}",
            root_label="same_repository", origin=code_origin,
            commit_sha=code_commit, branch=code_branch,
        ))
    else:
        sources.append(SourceRecord(
            source_id="docs", source_type="documentation_source", display_name=docs_root.name,
            root_label="separate_documentation_source", origin=docs_origin,
            commit_sha=docs_commit, branch=docs_branch,
        ))

    discovered: list[tuple[Path, Path, str, str, str | None]] = []
    if same_root:
        for path, kind, language in _file_candidates(code_root, allow_docs=True, allow_code=True):
            source_id = "docs" if kind == "documentation" else "code"
            discovered.append((path, code_root, source_id, kind, language))
    else:
        for path, kind, language in _file_candidates(code_root, allow_docs=False, allow_code=True):
            # If a separate docs directory is nested under the code checkout,
            # let the docs source own its contents so files are not duplicated.
            if path.resolve().is_relative_to(docs_root):
                continue
            discovered.append((path, code_root, "code", kind, language))
        for path, kind, language in _file_candidates(docs_root, allow_docs=True, allow_code=True):
            discovered.append((path, docs_root, "docs", kind, language))

    discovered.sort(key=lambda item: (item[2], item[0].as_posix().lower()))
    discovered_limit = max(0, len(discovered) - max_files)
    discovered = discovered[:max_files]
    file_records: list[FileRecord] = []
    chunks: list[Chunk] = []
    chunks_by_file: dict[tuple[str, str], list[Chunk]] = defaultdict(list)
    skipped_count = discovered_limit
    total_bytes = 0

    for path, root, source_id, file_kind, language in discovered:
        relative_path = _relative_posix(path, root)
        try:
            size = path.stat().st_size
        except OSError as error:
            skipped_count += 1
            file_records.append(FileRecord(
                source_id, source_id, relative_path, path.suffix.lower(), language,
                file_kind, 0, "", status="skipped", warning=f"stat failed: {error}",
            ))
            continue

        if size > max_file_bytes:
            skipped_count += 1
            file_records.append(FileRecord(
                source_id, source_id, relative_path, path.suffix.lower(), language,
                file_kind, size, "", status="skipped",
                warning=f"file exceeds {max_file_bytes} byte limit",
            ))
            continue
        if total_bytes + size > max_total_bytes:
            skipped_count += 1
            file_records.append(FileRecord(
                source_id, source_id, relative_path, path.suffix.lower(), language,
                file_kind, size, "", status="skipped",
                warning=f"repository exceeds {max_total_bytes} byte ingestion budget",
            ))
            continue
        text, warning = _read_text(path)
        if text is None:
            skipped_count += 1
            file_records.append(FileRecord(
                source_id, source_id, relative_path, path.suffix.lower(), language,
                file_kind, size, "", status="skipped", warning=warning,
            ))
            continue

        total_bytes += size
        if contains_probable_secret(text):
            skipped_count += 1
            file_records.append(FileRecord(
                source_id=source_id,
                source_type=source_id,
                path=relative_path,
                extension=path.suffix.lower(),
                language=language,
                file_kind=file_kind,
                size_bytes=size,
                content_hash="",
                status="skipped",
                warning="probable literal credential detected; file was not indexed",
            ))
            continue

        content_hash = sha256_text(text)
        raw_chunks = extract_file_chunks(text, path.suffix.lower(), file_kind, language)
        source_commit = code_commit if source_id == "code" or same_root else docs_commit
        file_chunks: list[Chunk] = []
        for raw in raw_chunks:
            raw_content = str(raw.get("content", ""))
            if not raw_content.strip():
                continue
            segments = _split_content_with_lines(raw_content)
            if not segments:
                continue
            for part_index, (content, relative_start, relative_end) in enumerate(segments):
                start_line = int(raw["start_line"]) + relative_start
                end_line = min(int(raw["end_line"]), int(raw["start_line"]) + relative_end)
                chunk_metadata = dict(raw.get("metadata") or {})
                if len(segments) > 1:
                    chunk_metadata.update({"part_index": part_index + 1, "part_count": len(segments)})
                chunk_data = {**raw, "content": content, "start_line": start_line, "end_line": end_line}
                chunk = Chunk(
                    chunk_id=_chunk_id(project_id, source_id, relative_path, chunk_data, source_commit),
                    project_id=project_id,
                    source_id=source_id,
                    source_type=("documentation" if file_kind == "documentation" else "configuration" if file_kind == "configuration" else "code"),
                    kind=raw["kind"],
                    path=relative_path,
                    start_line=start_line,
                    end_line=end_line,
                    content=content,
                    content_hash=sha256_text(content),
                    commit_sha=source_commit,
                    language=raw.get("language") or language,
                    symbol=raw.get("symbol"),
                    parent_symbol=raw.get("parent_symbol"),
                    section=raw.get("section"),
                    metadata=chunk_metadata,
                )
                file_chunks.append(chunk)
                chunks.append(chunk)

        file_records.append(FileRecord(
            source_id=source_id,
            source_type=source_id,
            path=relative_path,
            extension=path.suffix.lower(),
            language=language,
            file_kind=file_kind,
            size_bytes=size,
            content_hash=content_hash,
            chunk_count=len(file_chunks),
        ))
        chunks_by_file[(source_id, relative_path)].extend(file_chunks)

    summaries: list[FileSummary] = []
    for (source_id, path), file_chunks in sorted(chunks_by_file.items()):
        summaries.append(_build_file_summary(
            project_id, source_id, path, file_chunks, summary_scope="file"
        ))
        section_groups: dict[str, list[Chunk]] = defaultdict(list)
        for chunk in file_chunks:
            if chunk.section:
                section_groups[chunk.section].append(chunk)
        for section, section_chunks in sorted(section_groups.items()):
            summaries.append(_build_file_summary(
                project_id, source_id, path, section_chunks,
                summary_scope="section", section=section,
            ))

    code_languages = Counter(
        record.language for record in file_records
        if record.status == "indexed" and record.file_kind == "source" and record.language
    )
    kind_counts = Counter(chunk.kind for chunk in chunks)
    source_chunk_ids = [chunk.chunk_id for chunk in chunks]
    project_summary = {
        "project_id": project_id,
        "project_name": project_name,
        "summary_method": "metadata_only_v1",
        "is_llm_generated": False,
        "summary_text": (
            f"Ingested {sum(record.status == 'indexed' for record in file_records)} file(s), creating {len(chunks)} "
            f"traceable chunk(s). Content categories: "
            + ", ".join(f"{kind} ({count})" for kind, count in sorted(kind_counts.items()))
        ),
        "file_count": sum(record.status == "indexed" for record in file_records),
        "chunk_count": len(chunks),
        "kind_counts": dict(sorted(kind_counts.items())),
        "language_counts": dict(sorted(code_languages.items())),
        "source_chunk_ids": source_chunk_ids[:100],
        "note": "This is a metadata/extractive summary, not an LLM-generated semantic summary.",
    }

    fingerprint = stable_id(
        code_commit or "no-code-commit",
        docs_commit or "no-docs-commit",
        *(record.content_hash for record in file_records if record.content_hash),
        length=16,
    )
    snapshot_id = f"{(code_commit or 'working-tree')[:10]}-{fingerprint}"
    base_output = Path(output_dir).expanduser().resolve() if output_dir else Path.cwd() / ".docuguard" / "index"
    final_dir = base_output / project_id / snapshot_id

    # Prevent output from being written into a scanned root, except under the
    # reserved .docuguard directory which the scanner always excludes.
    for root in {code_root, docs_root}:
        try:
            relative_output = final_dir.relative_to(root)
            if relative_output.parts and relative_output.parts[0] != ".docuguard":
                raise IngestionError(
                    f"Output directory must be outside source roots or under .docuguard/: {final_dir}"
                )
        except ValueError:
            pass

    final_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "1.0",
        "project": {"project_id": project_id, "project_name": project_name},
        "snapshot": {
            "snapshot_id": snapshot_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "code_commit_sha": code_commit,
            "docs_commit_sha": docs_commit,
            "code_branch": code_branch,
            "docs_branch": docs_branch,
        },
        "sources": [source.to_dict() for source in sources],
        "counts": {
            "files": len(file_records),
            "indexed_files": sum(record.status == "indexed" for record in file_records),
            "chunks": len(chunks),
            "summaries": len(summaries), "skipped": skipped_count,
            "bytes_read": total_bytes,
            "discovered_but_not_processed_due_to_file_limit": discovered_limit,
        },
        "storage": {
            "files": "files.jsonl", "chunks": "chunks.jsonl",
            "summaries": "summaries.jsonl", "project_summary": "project_summary.json",
        },
        "future_rag": {
            "embeddings_created": False,
            "vector_store": None,
            "raw_chunks_preserved": True,
            "summary_method": "extractive_v1",
        },
    }

    _write_jsonl(final_dir / "files.jsonl", [record.to_dict() for record in file_records])
    _write_jsonl(final_dir / "chunks.jsonl", [chunk.to_dict() for chunk in chunks])
    _write_jsonl(final_dir / "summaries.jsonl", [summary.to_dict() for summary in summaries])
    _atomic_write_text(final_dir / "project_summary.json", json.dumps(project_summary, ensure_ascii=False, indent=2) + "\n")
    _atomic_write_text(final_dir / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    return IngestionResult(
        project_id=project_id,
        snapshot_id=snapshot_id,
        output_dir=str(final_dir),
        file_count=sum(record.status == "indexed" for record in file_records),
        chunk_count=len(chunks),
        summary_count=len(summaries),
        skipped_count=skipped_count,
        manifest_path=str(final_dir / "manifest.json"),
        chunks_path=str(final_dir / "chunks.jsonl"),
        summaries_path=str(final_dir / "summaries.jsonl"),
    )
