#!/usr/bin/env python3
# ==============================================================================
# session_snapshot.py - Memory-file snapshot tool
# ==============================================================================
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE file in the project root.
#
# Purpose:
#   Copy a Claude Code memory file from ~/.claude/projects/<project>/memory/
#   into the current git repository's backup/sessions/ directory, verify
#   the copy with SHA-256, and (optionally) enforce a retention count.
#
#   Used as the on-demand equivalent of the old /export muscle memory:
#   one command captures "where we are right now" and commits it to a
#   git-tracked location that survives local state loss.
#
#   See README.md in this directory for the full story.
# ==============================================================================

import argparse
import sys
from pathlib import Path
from typing import List, Optional

# Allow running as a module (python -m session_snapshot) or directly
# as a script (python session_snapshot/session_snapshot.py).
try:
    from .models import (
        BACKUP_FILENAME_RE,
        HashPair,
        RestoreRequest,
        RestoreResult,
        RetentionPolicy,
        SEPARATOR,
        SnapshotRequest,
        SnapshotResult,
        utc_timestamp_now,
    )
    from .adapters.filesystem import (
        copy_preserving_mtime,
        ensure_dir,
        list_group_backups,
        remove_file,
        unique_backup_path,
    )
    from .adapters.git_root import NotInsideGitRepositoryError, find_git_root
    from .adapters.hashing import sha256_file
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from session_snapshot.models import (  # type: ignore
        BACKUP_FILENAME_RE,
        HashPair,
        RestoreRequest,
        RestoreResult,
        RetentionPolicy,
        SEPARATOR,
        SnapshotRequest,
        SnapshotResult,
        utc_timestamp_now,
    )
    from session_snapshot.adapters.filesystem import (  # type: ignore
        copy_preserving_mtime,
        ensure_dir,
        list_group_backups,
        remove_file,
        unique_backup_path,
    )
    from session_snapshot.adapters.git_root import (  # type: ignore
        NotInsideGitRepositoryError,
        find_git_root,
    )
    from session_snapshot.adapters.hashing import sha256_file  # type: ignore


DEFAULT_RETAIN = 5
DEFAULT_DEST_SUBPATH = Path("backup") / "sessions"


# =============================================================================
# Backup flow
# =============================================================================


def take_snapshot(request: SnapshotRequest) -> SnapshotResult:
    """Run the backup flow and return the result.

    Fails loud on any SHA-256 mismatch: the destination file is removed
    before the function raises so the filesystem is never left with a
    corrupt copy.
    """
    source = request.source
    dest_dir = request.dest_dir
    original_basename = source.name
    timestamp = utc_timestamp_now()

    ensure_dir(dest_dir)
    destination = unique_backup_path(dest_dir, timestamp, original_basename)

    if request.dry_run:
        src_hash = sha256_file(source)
        return SnapshotResult(
            source=source,
            destination=destination,
            size_bytes=source.stat().st_size,
            hashes=HashPair(source_sha256=src_hash, destination_sha256=src_hash),
            purged=_peek_purge_candidate(dest_dir, original_basename, request.retention),
        )

    src_hash = sha256_file(source)
    copy_preserving_mtime(source, destination)
    dst_hash = sha256_file(destination)
    hashes = HashPair(source_sha256=src_hash, destination_sha256=dst_hash)
    if not hashes.verified:
        remove_file(destination)
        raise RuntimeError(
            f"SHA-256 mismatch after copy: source={src_hash} destination={dst_hash}. "
            f"Corrupt backup removed."
        )

    purged = _apply_retention(dest_dir, original_basename, destination, request.retention)

    return SnapshotResult(
        source=source,
        destination=destination,
        size_bytes=destination.stat().st_size,
        hashes=hashes,
        purged=purged,
    )


def _peek_purge_candidate(
    dest_dir: Path, original_basename: str, retention: RetentionPolicy
) -> Optional[Path]:
    """Return the file that retention WOULD purge in a non-dry-run.

    Used only by dry-run to preview the one-per-run purge.
    """
    if not retention.enabled:
        return None
    existing = list_group_backups(dest_dir, original_basename)
    # +1 accounts for the snapshot we would be adding in a real run.
    if len(existing) + 1 > retention.retain_count:
        return existing[0][1]
    return None


def _apply_retention(
    dest_dir: Path,
    original_basename: str,
    just_added: Path,
    retention: RetentionPolicy,
) -> Optional[Path]:
    """Remove at most one oldest backup if the group exceeds the retention count.

    Safety properties:

    - Only one file is purged per invocation, even if the count is
      badly exceeded. Convergence takes multiple runs; a single run
      can never cause a batch delete.
    - The file just added is never eligible for purge.
    - Only files matching the snapshot filename pattern in ``dest_dir``
      are candidates; foreign files (README, user-placed notes, etc.)
      are never touched.
    """
    if not retention.enabled:
        return None
    group = list_group_backups(dest_dir, original_basename)
    if len(group) <= retention.retain_count:
        return None

    # Oldest first from list_group_backups; skip the one we just
    # created even though it's almost certainly last.
    for _, path in group:
        if path != just_added:
            remove_file(path)
            return path
    return None


# =============================================================================
# Restore flow
# =============================================================================


def restore_snapshot(request: RestoreRequest) -> RestoreResult:
    """Copy a backup file back to its original-style name.

    Strips the ``<timestamp>__`` prefix (and any ``.N`` collision
    disambiguator) to recover the preserved original basename, then
    copies into the target directory with SHA-256 verification.
    """
    backup = request.backup
    match = BACKUP_FILENAME_RE.match(backup.name)
    if match is None:
        raise ValueError(
            f"not a snapshot backup filename (missing '<timestamp>__' prefix): "
            f"{backup.name}"
        )
    original_basename = match.group("original")
    destination = request.target_dir / original_basename

    if request.dry_run:
        src_hash = sha256_file(backup)
        return RestoreResult(
            backup=backup,
            destination=destination,
            size_bytes=backup.stat().st_size,
            hashes=HashPair(source_sha256=src_hash, destination_sha256=src_hash),
        )

    ensure_dir(request.target_dir)
    src_hash = sha256_file(backup)
    copy_preserving_mtime(backup, destination)
    dst_hash = sha256_file(destination)
    hashes = HashPair(source_sha256=src_hash, destination_sha256=dst_hash)
    if not hashes.verified:
        remove_file(destination)
        raise RuntimeError(
            f"SHA-256 mismatch after restore: backup={src_hash} "
            f"destination={dst_hash}. Corrupt restore removed."
        )
    return RestoreResult(
        backup=backup,
        destination=destination,
        size_bytes=destination.stat().st_size,
        hashes=hashes,
    )


# =============================================================================
# CLI
# =============================================================================


def _resolve_default_dest_dir(start: Optional[Path]) -> Path:
    """Return ``<git-root>/backup/sessions/`` for the caller's CWD."""
    root = find_git_root(start)
    return root / DEFAULT_DEST_SUBPATH


def _print_snapshot_result(result: SnapshotResult, dry_run: bool) -> None:
    tag = "[DRY-RUN] " if dry_run else ""
    print(f"{tag}source:       {result.source}")
    print(f"{tag}destination:  {result.destination}")
    print(f"{tag}size:         {result.size_bytes} bytes")
    print(f"{tag}sha256 src:   {result.hashes.source_sha256}")
    print(f"{tag}sha256 dst:   {result.hashes.destination_sha256}")
    print(f"{tag}verified:     {'OK' if result.hashes.verified else 'FAILED'}")
    if result.purged is not None:
        action = "would purge" if dry_run else "purged"
        print(f"{tag}retention:    {action} {result.purged.name}")
    else:
        print(f"{tag}retention:    no purge")


def _print_restore_result(result: RestoreResult, dry_run: bool) -> None:
    tag = "[DRY-RUN] " if dry_run else ""
    print(f"{tag}backup:       {result.backup}")
    print(f"{tag}destination:  {result.destination}")
    print(f"{tag}size:         {result.size_bytes} bytes")
    print(f"{tag}sha256 backup:      {result.hashes.source_sha256}")
    print(f"{tag}sha256 destination: {result.hashes.destination_sha256}")
    print(f"{tag}verified:     {'OK' if result.hashes.verified else 'FAILED'}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="session_snapshot",
        description=(
            "Back up a Claude Code memory file into the current git repo's "
            "backup/sessions/ directory, SHA-256 verified, with per-source "
            "retention. Restore mode reverses the operation."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--source",
        type=Path,
        help="File to back up (typically a memory file in ~/.claude/projects/<project>/memory/).",
    )
    mode.add_argument(
        "--restore",
        type=Path,
        help="Backup file to restore. The <timestamp>__ prefix is stripped "
        "to recover the original filename.",
    )

    parser.add_argument(
        "--dest-dir",
        type=Path,
        default=None,
        help="Destination directory. Defaults to <git-root>/backup/sessions/ "
        "when --source is used, and the memory file's original directory "
        "when --restore is used.",
    )
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=None,
        help="Alias for --dest-dir, primarily used with --restore for clarity.",
    )
    parser.add_argument(
        "--retain",
        type=int,
        default=DEFAULT_RETAIN,
        help=f"Maximum number of backups to keep per source file. "
        f"Default {DEFAULT_RETAIN}. Use 0 to disable retention. At most "
        f"one oldest backup is purged per invocation.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would happen without writing or deleting anything.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # --target-dir is an alias; prefer it if provided, else --dest-dir.
    effective_dest = args.target_dir if args.target_dir is not None else args.dest_dir

    try:
        if args.source is not None:
            source = args.source.expanduser().resolve()
            if not source.is_file():
                print(f"error: --source is not a file: {source}", file=sys.stderr)
                return 2
            if effective_dest is None:
                effective_dest = _resolve_default_dest_dir(source.parent)
            request = SnapshotRequest(
                source=source,
                dest_dir=effective_dest.expanduser().resolve(),
                retention=RetentionPolicy(retain_count=args.retain),
                dry_run=args.dry_run,
            )
            result = take_snapshot(request)
            _print_snapshot_result(result, dry_run=args.dry_run)
            return 0

        # --restore mode
        backup = args.restore.expanduser().resolve()
        if not backup.is_file():
            print(f"error: --restore is not a file: {backup}", file=sys.stderr)
            return 2
        if effective_dest is None:
            # No target given; default to ~/.claude/projects/<encoded>/memory/
            # only when we can infer it. The caller can always be explicit
            # via --target-dir; if not, we default to the backup file's own
            # directory, which is never destructive.
            effective_dest = backup.parent
        restore_request = RestoreRequest(
            backup=backup,
            target_dir=effective_dest.expanduser().resolve(),
            dry_run=args.dry_run,
        )
        restore_result = restore_snapshot(restore_request)
        _print_restore_result(restore_result, dry_run=args.dry_run)
        return 0

    except NotInsideGitRepositoryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print(
            "hint: run from inside a git repository, or pass --dest-dir explicitly.",
            file=sys.stderr,
        )
        return 3
    except (FileNotFoundError, PermissionError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
