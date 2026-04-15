# ==============================================================================
# migrate_to_backup_sessions/__init__.py - Rollout helper for backup/sessions
# ==============================================================================
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# ==============================================================================

"""
migrate_to_backup_sessions - Idempotent rollout helper that brings a
consumer project into conformance with the backup/sessions/
convention. See README.md in this directory for the full story.
"""

from .migrate_to_backup_sessions import (
    DEFAULT_SUBMODULE_REF,
    build_plan,
    execute_plan,
    main,
)
from .models import (
    Candidate,
    MigrationPlan,
    MigrationResult,
    Task,
    TaskKind,
    TaskOutcome,
)

__all__ = [
    "Candidate",
    "DEFAULT_SUBMODULE_REF",
    "MigrationPlan",
    "MigrationResult",
    "Task",
    "TaskKind",
    "TaskOutcome",
    "build_plan",
    "execute_plan",
    "main",
]

__version__ = "1.0.0"
