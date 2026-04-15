#!/usr/bin/env python3
# ==============================================================================
# adapters/hashing.py - SHA-256 adapter for jsonl_snapshot
# ==============================================================================
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE file in the project root.
# ==============================================================================

import gzip
import hashlib
from pathlib import Path


# 1 MiB chunks work well for both the uncompressed (potentially large,
# e.g. 109 MB) jsonl and the compressed (~10 MB) artifact.
_CHUNK_SIZE = 1 << 20


def sha256_file(path: Path) -> str:
    """Compute the SHA-256 hex digest of a file's raw byte contents."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sha256_gzipped(path: Path) -> str:
    """Compute the SHA-256 hex digest of a gzipped file's UNCOMPRESSED contents.

    Used to verify that a compressed backup decompresses back to a
    stream matching the original source hash, without actually writing
    the decompressed data to disk.
    """
    digest = hashlib.sha256()
    with gzip.open(path, "rb") as f:
        while True:
            chunk = f.read(_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()
