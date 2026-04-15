#!/usr/bin/env python3
# ==============================================================================
# adapters/filesystem.py - Filesystem operations for jsonl_snapshot
# ==============================================================================
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE file in the project root.
# ==============================================================================

import gzip
import shutil
from pathlib import Path
from typing import List, Tuple

from ..models import BACKUP_FILENAME_RE, SEPARATOR


# 1 MiB read/write chunks during compression. Keeps memory bounded
# regardless of input size and stays faster than the default
# gzip.GzipFile buffer for large files.
_COPY_CHUNK = 1 << 20


def ensure_dir(path: Path) -> None:
    """Create ``path`` and any missing parents."""
    path.mkdir(parents=True, exist_ok=True)


def gzip_compress_file(source: Path, destination_gz: Path) -> None:
    """Stream-compress ``source`` to ``destination_gz`` using gzip.

    Reads and writes in chunks so memory use is bounded regardless of
    the source size, which matters for session jsonls that can be
    100 MiB or more.
    """
    with source.open("rb") as src:
        with gzip.open(destination_gz, "wb") as dst:
            while True:
                chunk = src.read(_COPY_CHUNK)
                if not chunk:
                    break
                dst.write(chunk)


def gunzip_to_file(source_gz: Path, destination: Path) -> None:
    """Stream-decompress a .gz file to an uncompressed destination."""
    with gzip.open(source_gz, "rb") as src:
        with destination.open("wb") as dst:
            while True:
                chunk = src.read(_COPY_CHUNK)
                if not chunk:
                    break
                dst.write(chunk)


def remove_file(path: Path) -> None:
    """Delete a single file. No-op if the path does not exist."""
    if path.exists():
        path.unlink()


def list_group_backups(
    dest_dir: Path,
    original_basename: str,
) -> List[Tuple[str, Path]]:
    """Return compressed jsonl backups in ``dest_dir`` for a given source.

    Groups by the original basename (the portion between ``__`` and
    ``.gz``). Sorted by timestamp ascending (oldest first) so the
    retention logic can remove the first element.
    """
    if not dest_dir.is_dir():
        return []
    matches: List[Tuple[str, Path]] = []
    for entry in dest_dir.iterdir():
        if not entry.is_file():
            continue
        m = BACKUP_FILENAME_RE.match(entry.name)
        if m is None:
            continue
        if m.group("original") != original_basename:
            continue
        disambig = m.group("disambig") or "0"
        sort_key = f"{m.group('timestamp')}.{int(disambig):04d}"
        matches.append((sort_key, entry))
    matches.sort(key=lambda pair: pair[0])
    return matches


def unique_backup_paths(
    dest_dir: Path,
    timestamp: str,
    original_basename: str,
) -> Tuple[Path, Path]:
    """Return ``(<gz_path>, <sidecar_path>)`` guaranteed not to collide.

    The sidecar path is derived from the gz path by replacing the
    ``.gz`` suffix with ``.sha256``, so they always share the
    ``<timestamp><disambig>__<basename>`` root.
    """
    counter = 0
    while True:
        if counter == 0:
            prefix = timestamp
        else:
            prefix = f"{timestamp}.{counter}"
        gz = dest_dir / f"{prefix}{SEPARATOR}{original_basename}.gz"
        sidecar = dest_dir / f"{prefix}{SEPARATOR}{original_basename}.sha256"
        if not gz.exists() and not sidecar.exists():
            return gz, sidecar
        counter += 1
