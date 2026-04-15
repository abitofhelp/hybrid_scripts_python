#!/usr/bin/env python3
# ==============================================================================
# jsonl_snapshot.py - Compressed session-jsonl snapshot tool
# ==============================================================================
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE file in the project root.
#
# Purpose:
#   Back up a full Claude Code session jsonl (typically ~100 MB raw,
#   ~10 MB gzipped) into a gitignored backup/sessions/raw/ directory,
#   with dual-hash verification and a companion .sha256 sidecar file
#   capturing both the raw and compressed digests.
#
#   This is the forensic-tier backup paired with session_snapshot (the
#   strategic-tier memory-file backup). See README.md in this directory
#   for the full story.
# ==============================================================================

import argparse
import sys
from pathlib import Path
from typing import List, Optional

try:
    from .models import (
        BACKUP_FILENAME_RE,
        CompressionMetadata,
        HashPair,
        RestoreRequest,
        RestoreResult,
        RetentionPolicy,
        SEPARATOR,
        SnapshotRequest,
        SnapshotResult,
    )
    from .adapters.filesystem import (
        ensure_dir,
        gunzip_to_file,
        gzip_compress_file,
        list_group_backups,
        remove_file,
        unique_backup_paths,
    )
    from .adapters.git_root import NotInsideGitRepositoryError, find_git_root
    from .adapters.hashing import sha256_file, sha256_gzipped
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from jsonl_snapshot.models import (  # type: ignore
        BACKUP_FILENAME_RE,
        CompressionMetadata,
        HashPair,
        RestoreRequest,
        RestoreResult,
        RetentionPolicy,
        SEPARATOR,
        SnapshotRequest,
        SnapshotResult,
    )
    from jsonl_snapshot.adapters.filesystem import (  # type: ignore
        ensure_dir,
        gunzip_to_file,
        gzip_compress_file,
        list_group_backups,
        remove_file,
        unique_backup_paths,
    )
    from jsonl_snapshot.adapters.git_root import (  # type: ignore
        NotInsideGitRepositoryError,
        find_git_root,
    )
    from jsonl_snapshot.adapters.hashing import sha256_file, sha256_gzipped  # type: ignore

# Timestamp comes from session_snapshot so both tools emit the same
# UTC format without duplicating code. We reach into the sibling
# package rather than re-implementing.
try:
    from ..session_snapshot.models import utc_timestamp_now
except ImportError:
    # Fall through: tolerate being imported standalone by adding the
    # parent dir to sys.path. Already done above for the main-module
    # case.
    from session_snapshot.models import utc_timestamp_now  # type: ignore


DEFAULT_RETAIN = 3
DEFAULT_DEST_SUBPATH = Path("backup") / "sessions" / "raw"
DEFAULT_RESTORE_DIR = Path("/tmp")


# =============================================================================
# Backup flow
# =============================================================================


def take_snapshot(request: SnapshotRequest) -> SnapshotResult:
    """Compress ``request.source`` into the destination directory.

    Fails loud on any SHA-256 mismatch: the corrupt .gz (and sidecar
    if written) is removed before the function raises.
    """
    source = request.source
    dest_dir = request.dest_dir
    original_basename = source.name
    timestamp = utc_timestamp_now()

    ensure_dir(dest_dir)
    gz_path, sidecar_path = unique_backup_paths(dest_dir, timestamp, original_basename)

    src_hash = sha256_file(source)
    uncompressed_size = source.stat().st_size

    if request.dry_run:
        return SnapshotResult(
            source=source,
            destination_gz=gz_path,
            sidecar=sidecar_path,
            uncompressed_size_bytes=uncompressed_size,
            compression=CompressionMetadata(
                compressed_size_bytes=0, compressed_sha256="(dry-run)"
            ),
            hashes=HashPair(source_sha256=src_hash, destination_sha256=src_hash),
            purged=_peek_purge_candidate(dest_dir, original_basename, request.retention),
        )

    gzip_compress_file(source, gz_path)

    # Verify by hashing the decompressed stream of the .gz. This
    # proves gunzip round-trips to a byte-identical copy of the
    # source, so later restores are guaranteed to match.
    decompressed_hash = sha256_gzipped(gz_path)
    hashes = HashPair(source_sha256=src_hash, destination_sha256=decompressed_hash)
    if not hashes.verified:
        remove_file(gz_path)
        raise RuntimeError(
            f"SHA-256 mismatch after compress: source={src_hash} "
            f"decompressed={decompressed_hash}. Corrupt backup removed."
        )

    compressed_sha = sha256_file(gz_path)
    compressed_size = gz_path.stat().st_size
    compression = CompressionMetadata(
        compressed_size_bytes=compressed_size,
        compressed_sha256=compressed_sha,
    )

    _write_sidecar(
        sidecar_path=sidecar_path,
        source=source,
        raw_sha=src_hash,
        raw_size=uncompressed_size,
        gz_path=gz_path,
        gz_sha=compressed_sha,
        gz_size=compressed_size,
        timestamp=timestamp,
    )

    purged = _apply_retention(dest_dir, original_basename, gz_path, request.retention)

    return SnapshotResult(
        source=source,
        destination_gz=gz_path,
        sidecar=sidecar_path,
        uncompressed_size_bytes=uncompressed_size,
        compression=compression,
        hashes=hashes,
        purged=purged,
    )


def _write_sidecar(
    *,
    sidecar_path: Path,
    source: Path,
    raw_sha: str,
    raw_size: int,
    gz_path: Path,
    gz_sha: str,
    gz_size: int,
    timestamp: str,
) -> None:
    """Write the plain-text .sha256 sidecar describing both hashes.

    The sidecar is the ONLY persistent integrity record for this tier,
    because the backup target is gitignored. Keep the format stable
    and human-readable so restore tooling and external-storage
    consumers can parse it without ceremony.
    """
    content = (
        f"raw_sha256:   {raw_sha}  {source.name} ({raw_size} bytes)\n"
        f"gz_sha256:    {gz_sha}  {gz_path.name} ({gz_size} bytes)\n"
        f"snapshot_at:  {timestamp}\n"
        f"source_path:  {source}\n"
    )
    sidecar_path.write_text(content, encoding="utf-8")


def _peek_purge_candidate(
    dest_dir: Path, original_basename: str, retention: RetentionPolicy
) -> Optional[Path]:
    if not retention.enabled:
        return None
    existing = list_group_backups(dest_dir, original_basename)
    if len(existing) + 1 > retention.retain_count:
        return existing[0][1]
    return None


def _apply_retention(
    dest_dir: Path,
    original_basename: str,
    just_added: Path,
    retention: RetentionPolicy,
) -> Optional[Path]:
    """Remove at most one oldest .gz (and its sidecar) when exceeded.

    Same safety properties as session_snapshot: per-basename grouping,
    one purge per run, new file never eligible, only matching files
    touched. The sidecar that shares the same root name goes with its
    .gz.
    """
    if not retention.enabled:
        return None
    group = list_group_backups(dest_dir, original_basename)
    if len(group) <= retention.retain_count:
        return None
    for _, gz_path in group:
        if gz_path != just_added:
            # Replace only the final .gz extension with .sha256 so a
            # path like "<prefix>__name.jsonl.gz" becomes
            # "<prefix>__name.jsonl.sha256". A double with_suffix call
            # would strip two suffixes and point at the wrong file.
            sidecar = gz_path.with_suffix(".sha256")
            remove_file(gz_path)
            remove_file(sidecar)
            return gz_path
    return None


# =============================================================================
# Restore flow
# =============================================================================


def restore_snapshot(request: RestoreRequest) -> RestoreResult:
    """Decompress a backup .gz to its original filename in ``target_dir``.

    Two verification claims are tracked separately and reported
    distinctly in the CLI output:

    - **Archive integrity** — proved unconditionally by successful
      gunzip. If decompression fails or raises, the function raises
      and the restore is aborted.
    - **Source match** — proved ONLY when the companion ``.sha256``
      sidecar is present and its ``raw_sha256`` matches the restored
      file's hash. When the sidecar is missing (common in
      external-storage scenarios where the sidecar was not copied
      alongside the .gz), this claim is reported as UNVERIFIABLE.
      The restore still succeeds, but the CLI output makes the gap
      prominent so the operator can decide whether to trust the
      restored content.
    """
    backup_gz = request.backup_gz
    match = BACKUP_FILENAME_RE.match(backup_gz.name)
    if match is None:
        raise ValueError(
            f"not a jsonl_snapshot backup filename (expected "
            f"'<timestamp>__<name>.gz'): {backup_gz.name}"
        )
    original_basename = match.group("original")
    destination = request.target_dir / original_basename

    sidecar_raw_sha = _read_sidecar_raw_sha(backup_gz)
    sidecar_present = sidecar_raw_sha is not None

    if request.dry_run:
        preview_hash = sidecar_raw_sha if sidecar_present else sha256_gzipped(backup_gz)
        return RestoreResult(
            backup_gz=backup_gz,
            destination=destination,
            uncompressed_size_bytes=0,
            hashes=HashPair(
                source_sha256=preview_hash,
                destination_sha256=preview_hash,
            ),
            sidecar_present=sidecar_present,
            source_match_verified=sidecar_present,
        )

    ensure_dir(request.target_dir)
    gunzip_to_file(backup_gz, destination)
    restored_hash = sha256_file(destination)

    if sidecar_present:
        # Authoritative comparison: sidecar's raw_sha256 was captured
        # from the ORIGINAL source file at snapshot time, so a match
        # against restored_hash proves both archive integrity AND
        # source match simultaneously.
        expected_hash = sidecar_raw_sha
    else:
        # Fallback: rehash the decompressed stream. This proves
        # gunzip round-trips consistently (archive integrity) but
        # CANNOT prove the content matches the original source,
        # because the fallback hash is computed from the same
        # decompressed bytes we just wrote. We still return a
        # populated HashPair so the CLI output has something to
        # display, but source_match_verified is set False so callers
        # never mistake this for full verification.
        expected_hash = sha256_gzipped(backup_gz)

    hashes = HashPair(source_sha256=expected_hash, destination_sha256=restored_hash)
    if not hashes.verified:
        remove_file(destination)
        raise RuntimeError(
            f"SHA-256 mismatch after restore: expected={expected_hash} "
            f"restored={restored_hash}. Corrupt restore removed."
        )

    return RestoreResult(
        backup_gz=backup_gz,
        destination=destination,
        uncompressed_size_bytes=destination.stat().st_size,
        hashes=hashes,
        sidecar_present=sidecar_present,
        source_match_verified=sidecar_present,
    )


def _read_sidecar_raw_sha(backup_gz: Path) -> Optional[str]:
    """Read ``raw_sha256`` from the sibling .sha256 sidecar, if present."""
    # Replace only the final .gz extension with .sha256. See the
    # matching comment in _apply_retention for why the naive
    # double-with_suffix pattern is wrong.
    sidecar = backup_gz.with_suffix(".sha256")
    if not sidecar.is_file():
        return None
    try:
        for line in sidecar.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("raw_sha256:"):
                # Format: "raw_sha256:   <hex>  <filename> (<size> bytes)"
                parts = line.split()
                if len(parts) >= 2:
                    return parts[1]
    except OSError:
        return None
    return None


# =============================================================================
# CLI
# =============================================================================


def _resolve_default_dest_dir() -> Path:
    """Return ``<git-root>/backup/sessions/raw/`` for the caller's CWD.

    Intentionally uses the current working directory, NOT the source
    jsonl's parent directory. Session jsonls live in
    ``~/.claude/projects/<proj>/`` which is never a git repo; the
    destination should land in the repository the user is *currently
    working in*, which is their CWD.
    """
    root = find_git_root()
    return root / DEFAULT_DEST_SUBPATH


def _print_snapshot_result(result: SnapshotResult, dry_run: bool) -> None:
    tag = "[DRY-RUN] " if dry_run else ""
    print(f"{tag}source:            {result.source}")
    print(f"{tag}destination:       {result.destination_gz}")
    print(f"{tag}sidecar:           {result.sidecar}")
    print(f"{tag}uncompressed size: {result.uncompressed_size_bytes} bytes")
    print(f"{tag}compressed size:   {result.compression.compressed_size_bytes} bytes")
    print(f"{tag}sha256 raw src:    {result.hashes.source_sha256}")
    print(f"{tag}sha256 raw round:  {result.hashes.destination_sha256}")
    print(f"{tag}sha256 gz blob:    {result.compression.compressed_sha256}")
    print(f"{tag}verified:          {'OK' if result.hashes.verified else 'FAILED'}")
    if result.purged is not None:
        action = "would purge" if dry_run else "purged"
        print(f"{tag}retention:         {action} {result.purged.name}")
    else:
        print(f"{tag}retention:         no purge")


def _print_restore_result(result: RestoreResult, dry_run: bool) -> None:
    tag = "[DRY-RUN] " if dry_run else ""
    print(f"{tag}backup:              {result.backup_gz}")
    print(f"{tag}destination:         {result.destination}")
    print(f"{tag}uncompressed size:   {result.uncompressed_size_bytes} bytes")

    # Archive integrity is always OK at this point — if gunzip had
    # failed we would have raised before reaching this function. The
    # distinction that matters is whether we were also able to
    # cross-check the restored content against the original source
    # via the sidecar.
    print(f"{tag}archive integrity:   OK  (gunzip round-trip succeeded)")

    if result.source_match_verified:
        print(f"{tag}source-match:        OK  (verified against sidecar raw_sha256)")
        print(f"{tag}sha256 expected:     {result.hashes.source_sha256}")
        print(f"{tag}sha256 restored:     {result.hashes.destination_sha256}")
    else:
        # Make the unverifiable state visually unmissable: a WARNING
        # banner line plus an indented explanation of why. The CLI
        # exit code is still 0 — the restore is usable — but the
        # operator sees at a glance that source-match was not proved.
        print(f"{tag}source-match:        [WARNING] UNVERIFIABLE — sidecar .sha256 missing")
        print(f"{tag}                     The archive decompresses cleanly, so the")
        print(f"{tag}                     restored file is internally consistent with")
        print(f"{tag}                     the compressed backup. However, without the")
        print(f"{tag}                     sidecar we cannot prove the restored file")
        print(f"{tag}                     matches the ORIGINAL source captured at")
        print(f"{tag}                     snapshot time. Recover the sidecar from")
        print(f"{tag}                     external storage if source-match matters.")
        print(f"{tag}sha256 restored:     {result.hashes.destination_sha256}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jsonl_snapshot",
        description=(
            "Back up a Claude Code session .jsonl file into the current git "
            "repo's backup/sessions/raw/ directory, gzipped and SHA-256 "
            "verified, with a companion .sha256 sidecar. Restore mode "
            "decompresses to a target directory (default /tmp) and "
            "verifies."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--source", type=Path, help="Session .jsonl file to back up.")
    mode.add_argument("--restore", type=Path, help="Compressed backup to restore.")

    parser.add_argument(
        "--dest-dir",
        type=Path,
        default=None,
        help="Destination directory. Defaults to <git-root>/backup/sessions/raw/ "
        "for --source and /tmp for --restore.",
    )
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=None,
        help="Alias for --dest-dir, primarily used with --restore.",
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

    effective_dest = args.target_dir if args.target_dir is not None else args.dest_dir

    try:
        if args.source is not None:
            source = args.source.expanduser().resolve()
            if not source.is_file():
                print(f"error: --source is not a file: {source}", file=sys.stderr)
                return 2
            if effective_dest is None:
                effective_dest = _resolve_default_dest_dir()
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
            effective_dest = DEFAULT_RESTORE_DIR
        restore_request = RestoreRequest(
            backup_gz=backup,
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
