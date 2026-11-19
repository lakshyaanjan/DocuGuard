"""Stable service function intended to be called by a future webpage/API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .organizer import ingest_project


def ingest_local_project(request: dict[str, Any]) -> dict[str, Any]:
    """Ingest already-staged local sources and return a JSON-serialisable result.

    A future FastAPI route should stage uploads/clone repositories in a private
    temporary directory, validate ownership and size limits, then call this
    function. Never accept arbitrary server filesystem paths from an untrusted
    public client; local paths are appropriate only for a trusted backend.

    Required request fields:
      - code_root: path to a local checkout or extracted ZIP root
    Optional fields:
      - docs_root, project_name, output_dir, code_origin, docs_origin
    """
    if not isinstance(request, dict):
        raise TypeError("Ingestion request must be a JSON object.")
    code_root = request.get("code_root")
    if not code_root:
        raise ValueError("request.code_root is required.")
    result = ingest_project(
        repo_path=Path(code_root),
        docs_path=Path(request["docs_root"]) if request.get("docs_root") else None,
        project_name=request.get("project_name"),
        output_dir=request.get("output_dir"),
        code_origin=request.get("code_origin"),
        docs_origin=request.get("docs_origin"),
    )
    return result.to_dict()
