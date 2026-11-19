"""Typed records used by DocuGuard's ingestion and organisation layer.

The records intentionally contain no embeddings or LLM output. They preserve
source provenance so a later retrieval/LLM layer can cite exact evidence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class SourceRecord:
    source_id: str
    source_type: str
    display_name: str
    root_label: str
    origin: str | None = None
    commit_sha: str | None = None
    branch: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FileRecord:
    source_id: str
    source_type: str
    path: str
    extension: str
    language: str | None
    file_kind: str
    size_bytes: int
    content_hash: str
    chunk_count: int = 0
    status: str = "indexed"
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Chunk:
    chunk_id: str
    project_id: str
    source_id: str
    source_type: str
    kind: str
    path: str
    start_line: int
    end_line: int
    content: str
    content_hash: str
    commit_sha: str | None = None
    language: str | None = None
    symbol: str | None = None
    parent_symbol: str | None = None
    section: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class FileSummary:
    summary_id: str
    project_id: str
    source_id: str
    path: str
    summary_method: str
    summary_text: str
    source_chunk_ids: list[str]
    chunk_count: int
    summary_scope: str = "file"
    section: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class IngestionResult:
    project_id: str
    snapshot_id: str
    output_dir: str
    file_count: int
    chunk_count: int
    summary_count: int
    skipped_count: int
    manifest_path: str
    chunks_path: str
    summaries_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
