#!/usr/bin/env python3
# ==============================================================================
# session_snapshot/__main__.py - Module entry point
# ==============================================================================
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# ==============================================================================

"""Entry point for running ``python -m session_snapshot``."""

from .session_snapshot import main

if __name__ == "__main__":
    raise SystemExit(main())
