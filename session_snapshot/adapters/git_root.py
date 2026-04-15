#!/usr/bin/env python3
# ==============================================================================
# adapters/git_root.py - git repository root discovery for session_snapshot
# ==============================================================================
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE file in the project root.
#
# Purpose:
#   Resolve the current git repository root so session_snapshot can pick
#   a sensible default --dest-dir (<git-root>/backup/sessions/) without
#   needing per-project configuration.
# ==============================================================================

import subprocess
from pathlib import Path
from typing import Optional


class NotInsideGitRepositoryError(RuntimeError):
    """Raised when no git repository is found at or above the start directory."""


def find_git_root(start: Optional[Path] = None) -> Path:
    """Return the absolute path of the git repository containing ``start``.

    Uses ``git -C <start> rev-parse --show-toplevel`` so the answer is
    always git's own canonical idea of the repo root, including the
    correct handling of submodules, worktrees, and symlinked checkouts.

    Args:
        start: Directory to begin the search. Defaults to the current
               working directory.

    Raises:
        NotInsideGitRepositoryError: if no git repository is found at or
            above ``start``.
    """
    if start is None:
        start = Path.cwd()
    try:
        proc = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise NotInsideGitRepositoryError(
            f"no git repository found at or above {start}: "
            f"{exc.stderr.strip() or 'git rev-parse --show-toplevel failed'}"
        ) from exc
    except FileNotFoundError as exc:
        raise NotInsideGitRepositoryError(
            "git executable not found on PATH"
        ) from exc
    return Path(proc.stdout.strip()).resolve()
