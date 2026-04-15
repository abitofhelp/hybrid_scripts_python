#!/usr/bin/env python3
# ==============================================================================
# models.py - Data models for jsonl_snapshot
# ==============================================================================
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE file in the project root.
#
# Purpose:
#   Dataclasses and constants for the jsonl_snapshot forensic-tier
#   backup tool.
# ==============================================================================

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import re


# Separator between the UTC timestamp prefix and the preserved original
# filename. Must match session_snapshot's convention so both tools
# produce filenames with the same shape and recovery procedure.
SEPARATOR = "__"


# Regex matching a compressed jsonl backup filename produced by this tool:
#   <YYYYMMDDTHHMMSSZ>__<original-basename>.gz
# Same-second collisions use .N disambiguation like session_snapshot:
#   <YYYYMMDDTHHMMSSZ>.<N>__<original-basename>.gz
BACKUP_FILENAME_RE = re.compile(
    r"^(?P<timestamp>\d{8}T\d{6}Z)(?:\.(?P<disambig>\d+))?__(?P<original>.+)\.gz$"
)


@dataclass(frozen=True)
class HashPair:
    """SHA-256 hex digests of source and destination files.

    For jsonl_snapshot these represent the RAW (uncompressed) source
    jsonl and the RESTORED (uncompressed) file after gunzip. They MUST
    match for a successful snapshot.
    """
    source_sha256: str
    destination_sha256: str

    @property
    def verified(self) -> bool:
        return self.source_sha256 == self.destination_sha256


@dataclass(frozen=True)
class CompressionMetadata:
    """Size and hash of the compressed artifact.

    Written to the sidecar so external-storage consumers can verify
    the compressed blob itself (transport integrity) independently of
    decompressing and re-hashing the content.
    """
    compressed_size_bytes: int
    compressed_sha256: str


@dataclass(frozen=True)
class RetentionPolicy:
    """How many backups to keep per source-file group.

    Same semantics as session_snapshot: group by preserved original
    basename, keep the N most recent, purge at most one per invocation.
    """
    retain_count: int

    @property
    def enabled(self) -> bool:
        return self.retain_count > 0


@dataclass(frozen=True)
class SnapshotRequest:
    """A single jsonl backup request."""
    source: Path
    dest_dir: Path
    retention: RetentionPolicy
    dry_run: bool


@dataclass(frozen=True)
class SnapshotResult:
    """The outcome of a successful jsonl snapshot operation."""
    source: Path
    destination_gz: Path
    sidecar: Path
    uncompressed_size_bytes: int
    compression: CompressionMetadata
    hashes: HashPair
    purged: Optional[Path]  # None if retention did not purge


@dataclass(frozen=True)
class RestoreRequest:
    """A single jsonl restore request."""
    backup_gz: Path
    target_dir: Path
    dry_run: bool


@dataclass(frozen=True)
class RestoreResult:
    """The outcome of a successful jsonl restore operation."""
    backup_gz: Path
    destination: Path
    uncompressed_size_bytes: int
    hashes: HashPair
