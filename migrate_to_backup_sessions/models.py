#!/usr/bin/env python3
# ==============================================================================
# models.py - Data models for migrate_to_backup_sessions
# ==============================================================================
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE file in the project root.
# ==============================================================================

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional


class TaskKind(Enum):
    """The discrete operations this tool can perform.

    Each one is idempotent: running it against a project where the
    target state is already satisfied does nothing and reports
    ``already_done=True``.
    """
    CREATE_BACKUP_SESSIONS_DIR = "create_backup_sessions_dir"
    CREATE_BACKUP_SESSIONS_README = "create_backup_sessions_readme"
    CREATE_RAW_GITIGNORE = "create_raw_gitignore"
    ADD_EXPORTS_TO_GITIGNORE = "add_exports_to_gitignore"
    REMOVE_ZERO_BYTE_EXPORT = "remove_zero_byte_export"
    BUMP_SUBMODULE_POINTER = "bump_submodule_pointer"
    MIGRATE_MEANINGFUL_MD = "migrate_meaningful_md"


@dataclass(frozen=True)
class Task:
    """A single unit of work the tool can apply.

    ``target`` is the path (or submodule path) being operated on.
    ``detail`` is a short human-readable description used in both
    the planning report and the execution report.
    """
    kind: TaskKind
    target: Path
    detail: str


@dataclass(frozen=True)
class Candidate:
    """A non-zero-byte .md file in exports/ that may need migrating.

    The default mode lists candidates for human review rather than
    moving them, because judgment is required: some legacy exports
    are meaningful alignment notes or PR review packages worth
    preserving, others are stale scratch that should just be
    dropped. The ``--migrate-all-md`` mode converts every candidate
    into a MIGRATE_MEANINGFUL_MD task automatically.
    """
    source: Path             # absolute path to the file in exports/
    size_bytes: int
    commit_sha: Optional[str]         # first commit that added this file
    commit_timestamp_utc: Optional[str]  # YYYYMMDDTHHMMSSZ, or None if unknown
    target_name: str         # <timestamp>__<basename> planned destination name


@dataclass(frozen=True)
class OrphanTrackedExport:
    """A tracked, non-zero-byte, non-.md file in exports/.

    These are a distinct category from migration Candidates. They
    have real content but are not markdown artifacts the convention
    preserves — typically old Claude_Code_Export .txt transcripts
    from before the CLI regression. The tool does NOT touch them
    automatically: it surfaces them so the operator can decide
    whether to git rm (drop from HEAD, still in history) or
    manually git mv into backup/sessions/ for conversation-value
    preservation. Once exports/ is added to .gitignore, leaving
    them tracked means they stay in the index forever; the
    operator must untrack them explicitly.
    """
    source: Path
    size_bytes: int


@dataclass(frozen=True)
class MigrationPlan:
    """The full set of work to apply to a project.

    Produced by inspecting the project's current state. Consumers
    of this dataclass should always check ``candidates`` AND
    ``orphan_tracked_exports`` in addition to ``tasks`` because
    those two lists are human-judgment items that are NOT part of
    the automatic execution unless the caller opts in via
    ``--migrate-all-md`` (which only applies to candidates, not
    orphans).
    """
    project_root: Path
    submodule_ref_target: str
    tasks: List[Task] = field(default_factory=list)
    candidates: List[Candidate] = field(default_factory=list)
    orphan_tracked_exports: List[OrphanTrackedExport] = field(default_factory=list)
    already_done: List[str] = field(default_factory=list)

    @property
    def has_work(self) -> bool:
        return (
            bool(self.tasks)
            or bool(self.candidates)
            or bool(self.orphan_tracked_exports)
        )


@dataclass(frozen=True)
class TaskOutcome:
    """The result of executing one Task."""
    task: Task
    applied: bool            # False if it was already done or dry-run
    message: str


@dataclass(frozen=True)
class MigrationResult:
    """The cumulative result of executing a plan."""
    plan: MigrationPlan
    outcomes: List[TaskOutcome]
    dry_run: bool

    @property
    def applied_count(self) -> int:
        return sum(1 for o in self.outcomes if o.applied)

    @property
    def skipped_count(self) -> int:
        return sum(1 for o in self.outcomes if not o.applied)
