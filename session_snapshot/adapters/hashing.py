#!/usr/bin/env python3
# ==============================================================================
# adapters/hashing.py - SHA-256 adapter for session_snapshot
# ==============================================================================
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE file in the project root.
# ==============================================================================

import hashlib
from pathlib import Path


# 1 MiB chunks keep the working set small for files of any size. Even a
# 109 MB session jsonl hashes in tens of milliseconds with this chunk
# size, while never holding more than 1 MiB in memory at once.
_CHUNK_SIZE = 1 << 20


def sha256_file(path: Path) -> str:
    """Compute the SHA-256 hex digest of a file's contents.

    Streams the file in 1 MiB chunks so it works for any size without
    loading the whole file into memory. Raises FileNotFoundError if the
    path does not exist, and PermissionError if it cannot be read.
    """
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()
