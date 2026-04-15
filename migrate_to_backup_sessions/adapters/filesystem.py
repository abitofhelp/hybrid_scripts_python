#!/usr/bin/env python3
# ==============================================================================
# adapters/filesystem.py - Filesystem operations for the migration tool
# ==============================================================================
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE file in the project root.
# ==============================================================================

from pathlib import Path
from typing import List


def ensure_dir(path: Path) -> None:
    """Create ``path`` and any missing parents."""
    path.mkdir(parents=True, exist_ok=True)


def write_text_if_missing(path: Path, content: str) -> bool:
    """Write ``content`` to ``path`` only if the file does not exist.

    Returns True if a write happened, False if the path already
    existed (idempotency: leave existing content alone).
    """
    if path.exists():
        return False
    path.write_text(content, encoding="utf-8")
    return True


def file_size(path: Path) -> int:
    """Return file size in bytes, or -1 if the path cannot be stat'd."""
    try:
        return path.stat().st_size
    except OSError:
        return -1


def list_files_under(directory: Path, suffix: str = "") -> List[Path]:
    """Return all regular files directly under ``directory``.

    Non-recursive. Filters by suffix if provided (e.g. ``.md``).
    """
    if not directory.is_dir():
        return []
    result: List[Path] = []
    for entry in sorted(directory.iterdir()):
        if not entry.is_file():
            continue
        if suffix and not entry.name.endswith(suffix):
            continue
        result.append(entry)
    return result


def append_lines_if_missing(path: Path, block: str) -> bool:
    """Append ``block`` to ``path`` if its contents do not already contain it.

    Idempotency primitive used for .gitignore updates: check for a
    sentinel substring (the non-comment line that actually matches
    files) before writing, so rerunning the tool is a no-op.

    Args:
        path: File to check/append.
        block: Multi-line string to append if the sentinel is missing.
               The sentinel is any non-empty, non-comment line in block.

    Returns True if the block was appended, False if it was already
    present (or the file could not be created for some reason).
    """
    # Identify the sentinel: the first non-comment, non-empty line.
    sentinel = ""
    for line in block.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            sentinel = stripped
            break
    if not sentinel:
        return False

    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    for line in existing.splitlines():
        if line.strip() == sentinel:
            return False

    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(block.rstrip("\n") + "\n")
    return True
