"""DocuGuard data ingestion and organisation package."""

from .models import Chunk, FileRecord, FileSummary, IngestionResult, SourceRecord
from .organizer import IngestionError, ingest_project
from .service import ingest_local_project

__all__ = [
    "Chunk", "FileRecord", "FileSummary", "IngestionError", "IngestionResult",
    "SourceRecord", "ingest_local_project", "ingest_project",
]
