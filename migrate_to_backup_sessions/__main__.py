#!/usr/bin/env python3
# ==============================================================================
# migrate_to_backup_sessions/__main__.py - Module entry point
# ==============================================================================
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# ==============================================================================

"""Entry point for running ``python -m migrate_to_backup_sessions``."""

from .migrate_to_backup_sessions import main

if __name__ == "__main__":
    raise SystemExit(main())
