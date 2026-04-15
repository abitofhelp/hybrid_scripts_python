#!/usr/bin/env python3
# ==============================================================================
# adapters/filesystem.py - Filesystem operations for session_snapshot
# ==============================================================================
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE file in the project root.
#
# Purpose:
#   All disk operations the session_snapshot orchestration needs:
#   mkdir, copy, unlink, listing backups by source-file group. Keeping
#   them here means the main script never touches os/shutil directly
#   and the orchestration stays testable by faking this adapter.
# ==============================================================================

import shutil
from pathlib import Path
from typing import List, Tuple

from ..models import BACKUP_FILENAME_RE, SEPARATOR


def ensure_dir(path: Path) -> None:
    """Create ``path`` and any missing parents."""
    path.mkdir(parents=True, exist_ok=True)


def copy_preserving_mtime(source: Path, destination: Path) -> None:
    """Copy a file from ``source`` to ``destination``, preserving mtime."""
    shutil.copy2(source, destination)


def remove_file(path: Path) -> None:
    """Delete a single file. No-op if the path does not exist."""
    if path.exists():
        path.unlink()


def list_group_backups(
    dest_dir: Path,
    original_basename: str,
) -> List[Tuple[str, Path]]:
    """Return backups in ``dest_dir`` that belong to the same source file.

    Grouping is by the original basename — everything after the
    ``<timestamp>__`` prefix in the backup filename. The returned list
    is sorted by timestamp ascending (oldest first), which is what the
    retention logic needs.

    Args:
        dest_dir: Directory to scan.
        original_basename: Exact original filename to group by.

    Returns:
        List of (timestamp_string, path) tuples, sorted oldest first.
        Empty list if ``dest_dir`` does not exist or has no matching
        files.
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
        # Sort key includes the disambiguation counter so colliding
        # same-second backups remain in insertion order.
        timestamp_key = m.group("timestamp")
        disambig = m.group("disambig") or "0"
        matches.append((f"{timestamp_key}.{int(disambig):04d}", entry))
    matches.sort(key=lambda pair: pair[0])
    return matches


def unique_backup_path(dest_dir: Path, timestamp: str, original_basename: str) -> Path:
    """Return a backup path guaranteed not to collide with an existing file.

    The normal name is ``<dest_dir>/<timestamp>__<original_basename>``.
    If that exact path already exists (same-UTC-second collision), a
    small ``.N`` disambiguator is appended to the timestamp:
    ``<timestamp>.1__<name>``, ``<timestamp>.2__<name>``, and so on.

    This only triggers under automated-testing conditions or extremely
    rapid manual invocations; in ordinary use the plain form is used.
    """
    base_name = f"{timestamp}{SEPARATOR}{original_basename}"
    candidate = dest_dir / base_name
    if not candidate.exists():
        return candidate
    counter = 1
    while True:
        disambig_name = f"{timestamp}.{counter}{SEPARATOR}{original_basename}"
        candidate = dest_dir / disambig_name
        if not candidate.exists():
            return candidate
        counter += 1
