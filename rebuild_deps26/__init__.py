# ==============================================================================
# rebuild_deps26/__init__.py - Rebuild deps26 libraries from source
# ==============================================================================
# Copyright (c) 2025 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# ==============================================================================

"""
rebuild_deps26 - Clean and rebuild AdaCore 26.0 dependency libraries.

Usage:
    # From project root (recommended):
    python3 scripts/python/shared/rebuild_deps26/rebuild_deps26.py --clean

    # Or from scripts/python/shared directory:
    cd scripts/python/shared && python3 -m rebuild_deps26 --clean

See rebuild_deps26.py for full documentation.
"""

from .rebuild_deps26 import main

__all__ = [
    'main',
]

__version__ = '1.0.0'
