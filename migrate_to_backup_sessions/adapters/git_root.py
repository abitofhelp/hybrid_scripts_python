#!/usr/bin/env python3
# ==============================================================================
# adapters/git_root.py - git repository root discovery
# ==============================================================================
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE file in the project root.
# ==============================================================================

import subprocess
from pathlib import Path
from typing import Optional


class NotInsideGitRepositoryError(RuntimeError):
    """Raised when no git repository is found at or above the start directory."""


def find_git_root(start: Optional[Path] = None) -> Path:
    """Return the absolute path of the git repository containing ``start``.

    Duplicated from session_snapshot/adapters/git_root.py so this
    script remains self-contained and can be invoked independently.
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
