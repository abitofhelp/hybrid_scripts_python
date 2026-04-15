#!/usr/bin/env python3
# ==============================================================================
# models.py - Data models for session_snapshot
# ==============================================================================
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE file in the project root.
#
# Purpose:
#   Dataclasses and constants for the session_snapshot backup tool.
#
# ==============================================================================

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import re


# Separator between the UTC timestamp prefix and the preserved original
# filename in backup filenames. Double underscore was chosen because it
# does not occur in normal memory filenames, so the split is unambiguous
# and recovery (strip prefix, keep the rest) is a one-line operation.
SEPARATOR = "__"


# Regex matching a backup filename produced by this tool:
#   <YYYYMMDDTHHMMSSZ>__<original-basename>
# or with same-second collision disambiguation:
#   <YYYYMMDDTHHMMSSZ>.<N>__<original-basename>
BACKUP_FILENAME_RE = re.compile(
    r"^(?P<timestamp>\d{8}T\d{6}Z)(?:\.(?P<disambig>\d+))?__(?P<original>.+)$"
)


def utc_timestamp_now() -> str:
    """Return current UTC time as an ISO 8601 compact string.

    Format: YYYYMMDDTHHMMSSZ (e.g., 20260414T173000Z).
    """
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


@dataclass(frozen=True)
class HashPair:
    """SHA-256 hex digests of a source file and its backup destination.

    The two hashes MUST match for a successful snapshot. A mismatch means
    the copy was corrupted in transit and the destination is removed
    before the script exits non-zero.
    """
    source_sha256: str
    destination_sha256: str

    @property
    def verified(self) -> bool:
        return self.source_sha256 == self.destination_sha256


@dataclass(frozen=True)
class RetentionPolicy:
    """How many backups to keep per source-file group.

    Grouping is by the preserved original basename (everything after the
    <timestamp>__ prefix), not by the entire directory. This ensures
    event-driven one-off files (alignment notes, PR review packages)
    never get purged by heavy snapshot activity on a different file.

    A retain_count of 0 disables retention entirely (keep everything).
    """
    retain_count: int

    @property
    def enabled(self) -> bool:
        return self.retain_count > 0


@dataclass(frozen=True)
class SnapshotRequest:
    """A single backup request."""
    source: Path
    dest_dir: Path
    retention: RetentionPolicy
    dry_run: bool


@dataclass(frozen=True)
class SnapshotResult:
    """The outcome of a successful snapshot operation."""
    source: Path
    destination: Path
    size_bytes: int
    hashes: HashPair
    purged: Optional[Path]  # None if retention did not purge a file


@dataclass(frozen=True)
class RestoreRequest:
    """A single restore request."""
    backup: Path
    target_dir: Path
    dry_run: bool


@dataclass(frozen=True)
class RestoreResult:
    """The outcome of a successful restore operation."""
    backup: Path
    destination: Path
    size_bytes: int
    hashes: HashPair
