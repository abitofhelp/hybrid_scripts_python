#!/usr/bin/env python3
# ==============================================================================
# rebuild_deps26/__main__.py - Module entry point
# ==============================================================================
# Copyright (c) 2025 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# ==============================================================================

"""
Entry point for running rebuild_deps26 as a module.

Usage (from scripts/python/shared directory):
    cd scripts/python/shared && python3 -m rebuild_deps26 --clean

Or run directly from project root (recommended):
    python3 scripts/python/shared/rebuild_deps26/rebuild_deps26.py --clean
"""

from .rebuild_deps26 import main

if __name__ == '__main__':
    main()
