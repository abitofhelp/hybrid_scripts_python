#!/usr/bin/env python3
# ==============================================================================
# jsonl_snapshot/__main__.py - Module entry point
# ==============================================================================
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# ==============================================================================

"""Entry point for running ``python -m jsonl_snapshot``."""

from .jsonl_snapshot import main

if __name__ == "__main__":
    raise SystemExit(main())
