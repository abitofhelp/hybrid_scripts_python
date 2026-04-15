#!/usr/bin/env python3
# ==============================================================================
# adapters/git_ops.py - git subprocess operations
# ==============================================================================
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE file in the project root.
#
# Purpose:
#   All git subprocess calls the migration tool makes go through this
#   adapter so the orchestration layer never calls subprocess directly.
#   Keeps the main script testable by faking this module.
# ==============================================================================

import subprocess
from pathlib import Path
from typing import List, Optional, Tuple


def _run(cmd: List[str], cwd: Optional[Path] = None) -> str:
    """Run a git command and return its stdout, raising on non-zero exit."""
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout


def is_tracked(path: Path, repo: Path) -> bool:
    """Return True if ``path`` is tracked in the repo's index."""
    try:
        _run(
            ["git", "-C", str(repo), "ls-files", "--error-unmatch", str(path.relative_to(repo))],
        )
        return True
    except subprocess.CalledProcessError:
        return False


def list_tracked_under(directory: Path, repo: Path) -> List[Path]:
    """Return all tracked files directly under ``directory`` (non-recursive)."""
    rel = str(directory.relative_to(repo))
    try:
        stdout = _run(["git", "-C", str(repo), "ls-files", rel])
    except subprocess.CalledProcessError:
        return []
    result: List[Path] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        result.append(repo / line)
    return result


def git_rm(path: Path, repo: Path) -> None:
    """Run ``git rm`` on a single file inside ``repo``."""
    _run(["git", "-C", str(repo), "rm", str(path.relative_to(repo))])


def git_mv(source: Path, destination: Path, repo: Path) -> None:
    """Run ``git mv`` from source to destination inside ``repo``.

    Both paths must be within the repo. Destination parent directory
    must already exist (``mkdir -p`` is the caller's responsibility).
    """
    _run(
        [
            "git",
            "-C",
            str(repo),
            "mv",
            str(source.relative_to(repo)),
            str(destination.relative_to(repo)),
        ]
    )


def first_commit_timestamp_utc(file_path: Path, repo: Path) -> Tuple[Optional[str], Optional[str]]:
    """Return (commit_sha, UTC timestamp in YYYYMMDDTHHMMSSZ) for the commit
    that first added ``file_path`` to the index.

    Returns (None, None) if no such commit is found (file never committed
    or path outside the repo).
    """
    try:
        rel = str(file_path.relative_to(repo))
    except ValueError:
        return (None, None)
    try:
        out = _run(
            [
                "git",
                "-C",
                str(repo),
                "log",
                "--all",
                "--diff-filter=A",
                "--pretty=format:%H %cI",
                "--follow",
                "--",
                rel,
            ]
        )
    except subprocess.CalledProcessError:
        return (None, None)
    first_line = out.strip().splitlines()[0] if out.strip() else ""
    if not first_line:
        return (None, None)
    parts = first_line.split(maxsplit=1)
    if len(parts) != 2:
        return (None, None)
    sha, iso = parts
    # ISO 8601 with timezone to compact UTC form.
    # Example: "2026-04-13T20:42:28-07:00" -> "20260414T034228Z"
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(iso)
        dt_utc = dt.astimezone(timezone.utc)
        compact = dt_utc.strftime("%Y%m%dT%H%M%SZ")
    except (ValueError, AttributeError):
        return (sha, None)
    return (sha, compact)


def submodule_update_remote(submodule_path: Path, repo: Path) -> str:
    """Run ``git submodule update --remote`` on a single submodule.

    Returns the resulting HEAD SHA of the submodule after the update,
    or the empty string if the SHA could not be read.
    """
    _run(
        [
            "git",
            "-C",
            str(repo),
            "submodule",
            "update",
            "--remote",
            str(submodule_path.relative_to(repo)),
        ]
    )
    try:
        out = _run(
            ["git", "-C", str(repo / submodule_path.relative_to(repo)), "rev-parse", "HEAD"]
        )
        return out.strip()
    except subprocess.CalledProcessError:
        return ""


def current_submodule_sha(submodule_path: Path, repo: Path) -> Optional[str]:
    """Return the SHA the superproject's index currently tracks for the submodule.

    Uses ``git ls-tree HEAD`` so it reflects the committed pointer, not
    the working-tree state.
    """
    try:
        out = _run(
            [
                "git",
                "-C",
                str(repo),
                "ls-tree",
                "HEAD",
                str(submodule_path.relative_to(repo)),
            ]
        )
    except subprocess.CalledProcessError:
        return None
    parts = out.split()
    if len(parts) >= 3 and parts[1] == "commit":
        return parts[2]
    return None
