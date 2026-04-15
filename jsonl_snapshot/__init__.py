# ==============================================================================
# jsonl_snapshot/__init__.py - Compressed session-jsonl backup tool
# ==============================================================================
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# ==============================================================================

"""
jsonl_snapshot - Back up Claude Code session .jsonl files into a
gitignored backup/sessions/raw/ directory with gzip compression,
SHA-256 verification, and a companion .sha256 sidecar.

Forensic-tier backup paired with session_snapshot (strategic tier).
See README.md in this directory for the full story.
"""

from .models import (
    CompressionMetadata,
    HashPair,
    RestoreRequest,
    RestoreResult,
    RetentionPolicy,
    SnapshotRequest,
    SnapshotResult,
)
from .jsonl_snapshot import (
    main,
    restore_snapshot,
    take_snapshot,
)

__all__ = [
    "CompressionMetadata",
    "HashPair",
    "RestoreRequest",
    "RestoreResult",
    "RetentionPolicy",
    "SnapshotRequest",
    "SnapshotResult",
    "main",
    "restore_snapshot",
    "take_snapshot",
]

__version__ = "1.0.0"
