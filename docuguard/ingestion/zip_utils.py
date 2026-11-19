"""Defensive ZIP extraction for uploaded repository/documentation archives."""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path, PurePosixPath


class UnsafeArchiveError(ValueError):
    """Raised when an archive attempts path traversal or exceeds safety limits."""


def safe_extract_zip(
    archive_path: str | Path,
    destination: str | Path,
    *,
    max_files: int = 20_000,
    max_total_uncompressed: int = 200 * 1024 * 1024,
    max_single_file: int = 20 * 1024 * 1024,
) -> Path:
    """Extract a ZIP without Zip Slip, symlink or ZIP-bomb-style file expansion."""
    archive_path = Path(archive_path).resolve()
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    total_size = 0
    file_count = 0

    try:
        archive = zipfile.ZipFile(archive_path)
    except (OSError, zipfile.BadZipFile) as error:
        raise UnsafeArchiveError(f"Cannot read ZIP archive: {error}") from error

    with archive:
        for member in archive.infolist():
            raw_name = member.filename.replace("\\", "/")
            pure = PurePosixPath(raw_name)
            if pure.is_absolute() or any(part in {"..", ""} for part in pure.parts) or (pure.parts and ":" in pure.parts[0]):
                raise UnsafeArchiveError(f"Archive contains an unsafe path: {member.filename!r}")

            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise UnsafeArchiveError(f"Archive contains a symlink: {member.filename!r}")

            target = (destination / Path(*pure.parts)).resolve()
            try:
                target.relative_to(destination)
            except ValueError as error:
                raise UnsafeArchiveError(f"Archive path escapes extraction directory: {member.filename!r}") from error

            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue

            file_count += 1
            total_size += member.file_size
            if file_count > max_files:
                raise UnsafeArchiveError(f"Archive exceeds the {max_files} file limit.")
            if member.file_size > max_single_file:
                raise UnsafeArchiveError(f"Archive member exceeds the {max_single_file}-byte file limit: {member.filename}")
            if total_size > max_total_uncompressed:
                raise UnsafeArchiveError(f"Archive exceeds the {max_total_uncompressed}-byte uncompressed limit.")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member, "r") as source, target.open("wb") as output:
                written = 0
                while True:
                    block = source.read(1024 * 1024)
                    if not block:
                        break
                    written += len(block)
                    if written > max_single_file or written > member.file_size:
                        raise UnsafeArchiveError(f"Archive member expanded beyond its declared size: {member.filename}")
                    output.write(block)
                if written != member.file_size:
                    raise UnsafeArchiveError(f"Archive member size did not match its directory entry: {member.filename}")
    return destination
