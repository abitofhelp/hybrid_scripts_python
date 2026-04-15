# ==============================================================================
# session_snapshot/__init__.py - Memory-file snapshot tool
# ==============================================================================
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# ==============================================================================

"""
session_snapshot - Back up Claude Code memory files into a git-tracked
backup/sessions/ directory with SHA-256 verification and per-source
retention.

See README.md in this directory for the full story.
"""

from .models import (
    HashPair,
    RestoreRequest,
    RestoreResult,
    RetentionPolicy,
    SnapshotRequest,
    SnapshotResult,
    utc_timestamp_now,
)
from .session_snapshot import (
    main,
    restore_snapshot,
    take_snapshot,
)

__all__ = [
    "HashPair",
    "RestoreRequest",
    "RestoreResult",
    "RetentionPolicy",
    "SnapshotRequest",
    "SnapshotResult",
    "main",
    "restore_snapshot",
    "take_snapshot",
    "utc_timestamp_now",
]

__version__ = "1.0.0"
