#!/usr/bin/env python3
# ==============================================================================
# migrate_to_backup_sessions.py - Roll out the backup/sessions convention
# ==============================================================================
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE file in the project root.
#
# Purpose:
#   Idempotently bring a consumer project into conformance with the
#   backup/sessions/ convention defined by session_snapshot and
#   jsonl_snapshot. See README.md in this directory for the full
#   contract and the "how to use across projects" walkthrough.
# ==============================================================================

import argparse
import sys
from pathlib import Path
from typing import List, Optional

try:
    from .models import (
        Candidate,
        MigrationPlan,
        MigrationResult,
        OrphanTrackedExport,
        Task,
        TaskKind,
        TaskOutcome,
    )
    from .adapters.filesystem import (
        append_lines_if_missing,
        ensure_dir,
        file_size,
        list_files_under,
        write_text_if_missing,
    )
    from .adapters.git_ops import (
        current_submodule_sha,
        first_commit_timestamp_utc,
        git_mv,
        git_rm,
        is_tracked,
        list_tracked_under,
        submodule_update_remote,
    )
    from .adapters.git_root import NotInsideGitRepositoryError, find_git_root
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from migrate_to_backup_sessions.models import (  # type: ignore
        Candidate,
        MigrationPlan,
        MigrationResult,
        OrphanTrackedExport,
        Task,
        TaskKind,
        TaskOutcome,
    )
    from migrate_to_backup_sessions.adapters.filesystem import (  # type: ignore
        append_lines_if_missing,
        ensure_dir,
        file_size,
        list_files_under,
        write_text_if_missing,
    )
    from migrate_to_backup_sessions.adapters.git_ops import (  # type: ignore
        current_submodule_sha,
        first_commit_timestamp_utc,
        git_mv,
        git_rm,
        is_tracked,
        list_tracked_under,
        submodule_update_remote,
    )
    from migrate_to_backup_sessions.adapters.git_root import (  # type: ignore
        NotInsideGitRepositoryError,
        find_git_root,
    )


# The shared submodule that holds session_snapshot / jsonl_snapshot.
# Consumers mount it at this path by convention.
SUBMODULE_REL_PATH = Path("scripts") / "python" / "shared"

# Target state in each consumer after migration.
BACKUP_DIR_REL = Path("backup") / "sessions"
RAW_DIR_REL = BACKUP_DIR_REL / "raw"


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
#
# Kept inline rather than in separate files so the entire tool stays a
# single Python package with no external asset loading. The text is
# project-agnostic and does not reference any specific project name.


BACKUP_SESSIONS_README = """\
# backup/sessions/

Durable, git-tracked archive of session artifacts for this project.

## What lives here

Three kinds of files, all using the same filename convention so
chronological sort works across kinds:

```
<YYYYMMDDTHHMMSSZ>__<original-basename>
```

| Kind | How it gets here | Source of the content |
|---|---|---|
| `*_alignment_note.md` | Written directly by the assistant when a slice opens with a design decision. Committed with the slice's first commit. | The assistant's pre-coding review of the frozen docs + GPT check. |
| `*_pr_review_package.md` | Written directly by the assistant before a PR is opened. Committed with the slice's PR. | The assistant's self-contained review document for GPT. |
| `*` (time-driven snapshots) | Mirrored here by `scripts/python/shared/session_snapshot`, typically via the `/snapshot` custom slash command. | A Claude Code memory file from `~/.claude/projects/<encoded-project>/memory/`, preserved verbatim after the `<timestamp>__` prefix. |

Filenames sort naturally by UTC timestamp regardless of how many
different kinds coexist in the directory. Recovery of any file is a
plain `cp` with prefix strip (see
`scripts/python/shared/session_snapshot/README.md` for the
`--restore` tool or the manual procedure).

## Relationship to `backup/sessions/raw/`

`raw/` is **gitignored** and holds compressed full-session `.jsonl`
backups produced by `scripts/python/shared/jsonl_snapshot`. Those
files are large (~10 MB per snapshot) and intended for external
storage. Git-tracked files stay up here in `backup/sessions/`.

See `scripts/python/shared/jsonl_snapshot/README.md` for the full
forensic-tier workflow.

## What this is NOT

- **Not the Claude Code `/export` command output.** The CLI
  `/export` has been broken for some time; this directory is the
  workflow that replaces it.
- **Not a full conversation transcript.** Memory files are
  curated recap summaries written by the assistant at key
  workflow points. Use `jsonl_snapshot` and the raw session
  `.jsonl` under `~/.claude/projects/.../<uuid>.jsonl` for
  forensic recovery of verbatim conversation content.
- **Not a replacement for the Claude Code memory system.**
  Memory files in `~/.claude/projects/.../memory/` remain the
  auto-loaded source of strategic context at session start.
  This directory is the off-machine-durable backup copy that
  survives a local-state loss.
"""


RAW_GITIGNORE_CONTENT = """\
# Everything in this directory is gitignored on purpose: compressed
# session jsonls are large binary blobs that belong on external
# storage, not in git history. The directory itself is tracked
# (via this .gitignore file being the only tracked file) so fresh
# clones get a usable target for jsonl_snapshot without needing to
# run mkdir.
#
# See ../README.md and scripts/python/shared/jsonl_snapshot/README.md
# for the workflow that targets this directory.

*
!.gitignore
"""


EXPORTS_GITIGNORE_BLOCK = """\
# Claude Code session exports / ephemeral scratch space.
# The CLI /export command has been broken for some time (writes
# 0-byte stubs); durable session artifacts now live in
# backup/sessions/ via the session_snapshot tool in
# scripts/python/shared. The exports/ directory is kept as a local
# scratch path for cross-project context bouncing, but its contents
# are not git-tracked. See backup/sessions/README.md.
exports/
"""


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def build_plan(project_root: Path, submodule_ref_target: str) -> MigrationPlan:
    """Inspect ``project_root`` and compute the work needed.

    The returned plan is exhaustive for the mechanical tasks. Any
    non-zero-byte .md file in exports/ is reported as a Candidate
    (not a Task) — the caller decides whether to migrate them.
    """
    tasks: List[Task] = []
    already_done: List[str] = []
    candidates: List[Candidate] = []
    orphans: List[OrphanTrackedExport] = []

    backup_dir = project_root / BACKUP_DIR_REL
    backup_readme = backup_dir / "README.md"
    raw_dir = project_root / RAW_DIR_REL
    raw_gitignore = raw_dir / ".gitignore"
    root_gitignore = project_root / ".gitignore"
    exports_dir = project_root / "exports"

    # 1. backup/sessions/ directory + README
    if not backup_dir.is_dir():
        tasks.append(
            Task(
                kind=TaskKind.CREATE_BACKUP_SESSIONS_DIR,
                target=backup_dir,
                detail="create backup/sessions/ directory",
            )
        )
    else:
        already_done.append("backup/sessions/ exists")

    if not backup_readme.is_file():
        tasks.append(
            Task(
                kind=TaskKind.CREATE_BACKUP_SESSIONS_README,
                target=backup_readme,
                detail="write backup/sessions/README.md",
            )
        )
    else:
        already_done.append("backup/sessions/README.md exists")

    # 2. backup/sessions/raw/.gitignore
    if not raw_gitignore.is_file():
        tasks.append(
            Task(
                kind=TaskKind.CREATE_RAW_GITIGNORE,
                target=raw_gitignore,
                detail="write backup/sessions/raw/.gitignore",
            )
        )
    else:
        already_done.append("backup/sessions/raw/.gitignore exists")

    # 3. Add exports/ to .gitignore
    existing_root_gitignore = (
        root_gitignore.read_text(encoding="utf-8")
        if root_gitignore.is_file()
        else ""
    )
    if "exports/" not in existing_root_gitignore.splitlines():
        tasks.append(
            Task(
                kind=TaskKind.ADD_EXPORTS_TO_GITIGNORE,
                target=root_gitignore,
                detail="add exports/ entry to root .gitignore",
            )
        )
    else:
        already_done.append("exports/ already in .gitignore")

    # 4. Classify tracked files under exports/:
    #    - 0 bytes  -> auto-remove task (safe, no content loss)
    #    - .md file -> migration candidate (human review; optionally
    #                  auto-migrate via --migrate-all-md)
    #    - other    -> orphan (human review; NOT auto-handled because
    #                  they typically have real content of uncertain
    #                  value — e.g., large .txt Claude_Code_Export
    #                  transcripts from before the /export regression —
    #                  and the operator must decide git rm vs manual
    #                  migration)
    tracked_exports = list_tracked_under(exports_dir, project_root) if exports_dir.is_dir() else []
    for tracked in tracked_exports:
        size = file_size(tracked)
        if size == 0:
            tasks.append(
                Task(
                    kind=TaskKind.REMOVE_ZERO_BYTE_EXPORT,
                    target=tracked,
                    detail=f"git rm {tracked.relative_to(project_root)} (0 bytes)",
                )
            )
        elif tracked.suffix == ".md":
            sha, ts = first_commit_timestamp_utc(tracked, project_root)
            timestamp_part = ts if ts else "UNKNOWN"
            target_name = f"{timestamp_part}__{tracked.name}"
            candidates.append(
                Candidate(
                    source=tracked,
                    size_bytes=size,
                    commit_sha=sha,
                    commit_timestamp_utc=ts,
                    target_name=target_name,
                )
            )
        else:
            orphans.append(OrphanTrackedExport(source=tracked, size_bytes=size))

    # 5. Submodule pointer bump (always planned; executor decides no-op)
    current_sha = current_submodule_sha(project_root / SUBMODULE_REL_PATH, project_root)
    if current_sha != submodule_ref_target:
        tasks.append(
            Task(
                kind=TaskKind.BUMP_SUBMODULE_POINTER,
                target=project_root / SUBMODULE_REL_PATH,
                detail=(
                    f"bump {SUBMODULE_REL_PATH} submodule: "
                    f"{(current_sha or '<missing>')[:7]} -> {submodule_ref_target[:7]}"
                ),
            )
        )
    else:
        already_done.append(
            f"{SUBMODULE_REL_PATH} submodule already at {submodule_ref_target[:7]}"
        )

    return MigrationPlan(
        project_root=project_root,
        submodule_ref_target=submodule_ref_target,
        tasks=tasks,
        candidates=candidates,
        orphan_tracked_exports=orphans,
        already_done=already_done,
    )


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def execute_plan(
    plan: MigrationPlan,
    *,
    dry_run: bool,
    migrate_all_md: bool,
) -> MigrationResult:
    """Apply ``plan`` to the project.

    If ``migrate_all_md`` is True, every candidate is also moved into
    backup/sessions/ via ``git mv`` with its UTC-prefixed target name.
    Candidates without a commit timestamp are skipped with a warning.
    Nothing is committed; all changes are left staged for human
    review.
    """
    outcomes: List[TaskOutcome] = []

    for task in plan.tasks:
        outcomes.append(_apply_task(task, plan.project_root, dry_run=dry_run))

    if migrate_all_md:
        for candidate in plan.candidates:
            outcomes.append(
                _apply_candidate(candidate, plan.project_root, dry_run=dry_run)
            )

    return MigrationResult(plan=plan, outcomes=outcomes, dry_run=dry_run)


def _apply_task(task: Task, repo: Path, *, dry_run: bool) -> TaskOutcome:
    """Dispatch a single Task to the appropriate adapter call."""
    if dry_run:
        return TaskOutcome(task=task, applied=False, message=f"would: {task.detail}")

    if task.kind == TaskKind.CREATE_BACKUP_SESSIONS_DIR:
        ensure_dir(task.target)
        return TaskOutcome(task=task, applied=True, message=f"created {task.target.relative_to(repo)}")

    if task.kind == TaskKind.CREATE_BACKUP_SESSIONS_README:
        ensure_dir(task.target.parent)
        wrote = write_text_if_missing(task.target, BACKUP_SESSIONS_README)
        return TaskOutcome(
            task=task,
            applied=wrote,
            message=(
                f"wrote {task.target.relative_to(repo)}"
                if wrote
                else "already present"
            ),
        )

    if task.kind == TaskKind.CREATE_RAW_GITIGNORE:
        ensure_dir(task.target.parent)
        wrote = write_text_if_missing(task.target, RAW_GITIGNORE_CONTENT)
        return TaskOutcome(
            task=task,
            applied=wrote,
            message=(
                f"wrote {task.target.relative_to(repo)}"
                if wrote
                else "already present"
            ),
        )

    if task.kind == TaskKind.ADD_EXPORTS_TO_GITIGNORE:
        appended = append_lines_if_missing(task.target, EXPORTS_GITIGNORE_BLOCK)
        return TaskOutcome(
            task=task,
            applied=appended,
            message=(
                "appended exports/ block"
                if appended
                else "exports/ already ignored"
            ),
        )

    if task.kind == TaskKind.REMOVE_ZERO_BYTE_EXPORT:
        git_rm(task.target, repo)
        return TaskOutcome(
            task=task,
            applied=True,
            message=f"git rm {task.target.relative_to(repo)}",
        )

    if task.kind == TaskKind.BUMP_SUBMODULE_POINTER:
        new_sha = submodule_update_remote(task.target, repo)
        return TaskOutcome(
            task=task,
            applied=True,
            message=f"submodule updated to {new_sha[:7] if new_sha else '<unknown>'}",
        )

    return TaskOutcome(
        task=task, applied=False, message=f"unknown task kind: {task.kind}"
    )


def _apply_candidate(candidate: Candidate, repo: Path, *, dry_run: bool) -> TaskOutcome:
    """Migrate a candidate .md file into backup/sessions/ via git mv."""
    if candidate.commit_timestamp_utc is None:
        return TaskOutcome(
            task=Task(
                kind=TaskKind.MIGRATE_MEANINGFUL_MD,
                target=candidate.source,
                detail=f"migrate {candidate.source.name} (no commit timestamp)",
            ),
            applied=False,
            message=(
                "skipped: cannot derive UTC timestamp from git history "
                "(file never committed or outside repo)"
            ),
        )

    destination = repo / BACKUP_DIR_REL / candidate.target_name
    task = Task(
        kind=TaskKind.MIGRATE_MEANINGFUL_MD,
        target=candidate.source,
        detail=f"git mv {candidate.source.relative_to(repo)} -> {destination.relative_to(repo)}",
    )
    if dry_run:
        return TaskOutcome(task=task, applied=False, message=f"would: {task.detail}")

    ensure_dir(destination.parent)
    git_mv(candidate.source, destination, repo)
    return TaskOutcome(task=task, applied=True, message=task.detail)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


# Default target SHA for the shared submodule. Kept in sync with the
# current hybrid_scripts_python main HEAD at the time this tool ships.
# Callers can override with --submodule-ref.
DEFAULT_SUBMODULE_REF = "a3ace70312030365d51875136890bec9a904fd7e"


def _print_plan(plan: MigrationPlan) -> None:
    print(f"project root:    {plan.project_root}")
    print(f"target submodule: {plan.submodule_ref_target[:12]}")
    print()
    if plan.already_done:
        print("already done:")
        for item in plan.already_done:
            print(f"  - {item}")
        print()
    if plan.tasks:
        print(f"planned tasks ({len(plan.tasks)}):")
        for task in plan.tasks:
            print(f"  - [{task.kind.value}] {task.detail}")
        print()
    else:
        print("planned tasks: none (project already conforms)")
        print()
    if plan.candidates:
        print(f"non-zero-byte .md candidates in exports/ ({len(plan.candidates)}):")
        for c in plan.candidates:
            ts = c.commit_timestamp_utc or "UNKNOWN"
            print(
                f"  - {c.source.name} ({c.size_bytes} bytes, "
                f"first-added {ts}) -> {c.target_name}"
            )
        print(
            "  (these are NOT migrated automatically — pass --migrate-all-md "
            "to move them via git mv)"
        )
        print()
    else:
        print("non-zero-byte .md candidates: none")
        print()

    if plan.orphan_tracked_exports:
        print(
            f"[WARNING] orphan tracked non-.md files in exports/ "
            f"({len(plan.orphan_tracked_exports)}):"
        )
        for o in plan.orphan_tracked_exports:
            print(f"  - {o.source.relative_to(plan.project_root)} ({o.size_bytes} bytes)")
        print(
            "  These files have real content but are NOT .md artifacts the"
        )
        print(
            "  convention preserves (typically old Claude_Code_Export .txt"
        )
        print(
            "  transcripts). The tool will NOT touch them automatically."
        )
        print(
            "  Adding exports/ to .gitignore does NOT untrack them; they"
        )
        print(
            "  will remain in the git index until you handle them manually:"
        )
        print()
        print(
            "    option A (usual):  git rm <path>    # drop from HEAD,"
        )
        print(
            "                                        # history preserved"
        )
        print(
            "    option B (rare):   git mv <path> backup/sessions/<utc-prefixed-name>"
        )
        print(
            "                                        # preserve as conversation"
        )
        print(
            "                                        # artifact"
        )
        print()
    else:
        print("orphan tracked non-.md files in exports/: none")
        print()


def _print_outcomes(result: MigrationResult) -> None:
    tag = "[DRY-RUN] " if result.dry_run else ""
    print(f"{tag}execution summary:")
    if not result.outcomes:
        print(f"{tag}  (nothing to do)")
        return
    for o in result.outcomes:
        mark = "+" if o.applied else "."
        print(f"{tag}  {mark} {o.message}")
    print(
        f"{tag}applied: {result.applied_count}  skipped/already-done: "
        f"{result.skipped_count}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="migrate_to_backup_sessions",
        description=(
            "Idempotently bring a consumer project into conformance with "
            "the backup/sessions/ convention: create the tracked "
            "directories, write the README + raw/.gitignore, add exports/ "
            "to .gitignore, git rm any tracked 0-byte exports stubs, and "
            "bump the scripts/python/shared submodule pointer. Leaves "
            "everything staged for human review; never commits."
        ),
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root. Defaults to git root of the current working directory.",
    )
    parser.add_argument(
        "--submodule-ref",
        default=DEFAULT_SUBMODULE_REF,
        help=f"Target SHA for the scripts/python/shared submodule pointer. "
        f"Default: {DEFAULT_SUBMODULE_REF[:12]} (hybrid_scripts_python main).",
    )
    parser.add_argument(
        "--migrate-all-md",
        action="store_true",
        help="Also git mv every non-zero-byte .md file in exports/ into "
        "backup/sessions/ using its first-commit UTC timestamp. Without "
        "this flag, candidates are listed but not moved.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would happen without writing, deleting, or "
        "moving anything.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.project_root is None:
            project_root = find_git_root()
        else:
            project_root = args.project_root.expanduser().resolve()
            if not project_root.is_dir():
                print(
                    f"error: --project-root is not a directory: {project_root}",
                    file=sys.stderr,
                )
                return 2

        plan = build_plan(project_root, submodule_ref_target=args.submodule_ref)
        _print_plan(plan)

        if not plan.has_work:
            print("nothing to do; project already conforms.")
            return 0

        result = execute_plan(
            plan, dry_run=args.dry_run, migrate_all_md=args.migrate_all_md
        )
        _print_outcomes(result)

        if not args.dry_run and plan.candidates and not args.migrate_all_md:
            print()
            print(
                "NOTE: non-zero-byte .md candidates were NOT migrated. "
                "Review the list above and either:"
            )
            print("  - rerun with --migrate-all-md to move all of them, or")
            print(
                "  - git mv selected files manually and git rm the rest, then"
            )
            print("    commit everything together."
            )
        return 0

    except NotInsideGitRepositoryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(
            "hint: cd into a project repository, or pass --project-root.",
            file=sys.stderr,
        )
        return 3
    except (FileNotFoundError, PermissionError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
