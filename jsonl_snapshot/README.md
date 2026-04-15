# jsonl_snapshot

One-sentence purpose: **back up a full Claude Code session `.jsonl`
file into a gitignored `backup/sessions/raw/` directory with gzip
compression, SHA-256 verification, and a companion `.sha256` sidecar
recording both the uncompressed and compressed digests.**

This is the **forensic-tier** backup, paired with
[`session_snapshot`](../session_snapshot/README.md) (the
strategic-tier memory-file backup).

---

## When to use

- **Routine**: occasional full-session backups for "just in case"
  forensic recovery, copied to external storage as part of your
  end-of-day or end-of-week workflow.
- **Before risky operations**: when you're about to do something that
  might destabilize Claude Code's state (destructive git operations,
  system updates, `~/.claude` surgery).
- **On-demand forensic capture**: when you need the exact byte
  sequence of a past conversation — the memory-file snapshot captures
  decisions but not raw tool output, stack traces, or verbatim
  assistant turns.

For the common "save this moment in time" workflow, use
`session_snapshot` instead. This tool is the heavier complement.

## What it backs up

Claude Code session jsonl files, typically at
`~/.claude/projects/<encoded-project>/<session-uuid>.jsonl`. These can
be large (50–200 MB for a busy day of work) because they contain
every tool result, every file read, every assistant turn, and every
file-history snapshot the CC harness recorded during the session.

## Where backups land

Default: `<git-root>/backup/sessions/raw/` of the current project,
resolved via `git rev-parse --show-toplevel`.

**The `raw/` subdirectory is gitignored** — a compressed jsonl is a
binary blob that bloats git history fast, and the routine recovery
case rarely needs it. You are expected to copy the `.gz` files to
**external storage** (external drive, cloud backup, NAS rsync) as
your durability layer. The script supports that workflow but does not
do the copy itself.

Override with `--dest-dir`.

## Filename convention

```
<YYYYMMDDTHHMMSSZ>__<original-basename>.gz
<YYYYMMDDTHHMMSSZ>__<original-basename>.sha256    (sidecar)
```

Same `<timestamp>__<basename>` convention as `session_snapshot`, with
`.gz` for the compressed payload and `.sha256` for the sidecar. Both
share the exact same root, so sorting keeps them adjacent and
recovery can always find one from the other.

Same-UTC-second collisions use `.N` disambiguation (`<timestamp>.1__...`),
matching `session_snapshot`.

## SHA-256 verification

Every snapshot does three hash computations:

| Hash | What it verifies |
|---|---|
| `raw_sha256` (source) | The original uncompressed jsonl at snapshot time. |
| Decompressed round-trip | `gunzip(destination.gz)` is byte-identical to the source. Proved by hashing the decompressed stream without writing it to disk. |
| `gz_sha256` (compressed) | The `.gz` file itself. This is the "transport integrity" hash — verify this after copying the `.gz` to external storage to prove the transfer was clean. |

Any mismatch between `raw_sha256` and the decompressed round-trip
fails the snapshot: the corrupt `.gz` is removed and the script exits
non-zero. There is no silent corruption path.

## Sidecar file

Unlike `session_snapshot`, this tool writes a plain-text `.sha256`
sidecar next to each `.gz` because the backup destination is
**gitignored**. Git is not the integrity backstop for this tier, so
the sidecar IS the persistent integrity record.

Sidecar content:

```
raw_sha256:   3f4a9b...  c84f8b1c-ad37-40a0-8e01-fc28915273a4.jsonl (109443468 bytes)
gz_sha256:    7e21d8...  20260414T173000Z__c84f8b1c-...-fc28915273a4.jsonl.gz (10485760 bytes)
snapshot_at:  20260414T173000Z
source_path:  /Users/mike/.claude/projects/.../c84f8b1c-ad37-40a0-8e01-fc28915273a4.jsonl
```

Plain text is parseable by humans, shell tools, and any future
recovery script.

## Retention

Per-source-file grouping, default `--retain 3`. The lower default
than `session_snapshot` (which defaults to 5) reflects the size
difference: jsonl backups are ~10 MB compressed each, and they live
in a gitignored directory where purges are **true deletions** (no
git history fallback). Three recent backups is a sensible local
working-set ceiling; anything beyond that lives on external storage.

When retention purges a `.gz`, its sibling `.sha256` sidecar goes
with it. Same-run one-purge-maximum rule as `session_snapshot`.

`--retain 0` disables retention entirely.

## Mid-session vs end-of-session snapshots

The session jsonl is an **append-only file**. A mid-session `cp`
captures everything up to that moment, possibly missing the last one
or two records that have not yet been flushed to disk. That is
acceptable for routine backups.

For a **guaranteed-complete** snapshot, exit Claude Code first, then
run the tool. Exiting is not strictly necessary but eliminates any
in-flight write race.

In practice:

| Case | Approach |
|---|---|
| Routine backup during work | Mid-session, no exit |
| End-of-day archive | Either; mid-session is fine |
| Before a destructive operation | Exit first for a clean capture |

## Recovery

### Option 1: `--restore` mode (recommended)

```
jsonl_snapshot --restore backup/sessions/raw/20260414T173000Z__c84f8b1c-...-fc28915273a4.jsonl.gz
```

Decompresses into `/tmp` by default (override with `--target-dir`),
with SHA-256 verification against the sidecar's `raw_sha256`. If the
sidecar is missing (externally stored copy lost its sidecar),
verification falls back to rehashing the decompressed stream against
itself — which still proves decompression succeeded, just not that
the content matches the original.

After restore, tell Claude where the file is and Claude will read it
in slices (tail, grep-first, chunked scan — see the notes below).

### Option 2: plain `gunzip`

```
gunzip -c backup/sessions/raw/20260414T173000Z__<uuid>.jsonl.gz \
  > /tmp/<uuid>.jsonl
sha256sum /tmp/<uuid>.jsonl   # compare against the .sha256 sidecar's raw_sha256
```

## Working with a 100 MB jsonl

A restored jsonl is too large for Claude to read into context in a
single Read call. Effective strategies:

- **Tail read** — read the last N lines for "what happened most
  recently"
- **Grep-first extraction** — `rg 'pattern' /tmp/<file>.jsonl` filters
  to a handful of matching lines that Claude can then Read in full
- **Chunked scan** — Read 2000-line chunks sequentially, processing
  each, for exhaustive forensics

The point of the forensic backup is **targeted queries with known
intent**, not full-transcript ingestion. You tell Claude what
question to answer; Claude picks the right strategy for the file.

## CLI reference

```
jsonl_snapshot [--source FILE | --restore FILE]
               [--dest-dir DIR]
               [--target-dir DIR]
               [--retain N]
               [--dry-run]
```

Flags:

| Flag | Purpose | Default |
|---|---|---|
| `--source FILE` | Back up this session jsonl. | — |
| `--restore FILE` | Decompress this backup to `--target-dir`. | — |
| `--dest-dir DIR` | Destination for `--source`. | `<git-root>/backup/sessions/raw/` |
| `--target-dir DIR` | Destination for `--restore`. Alias for `--dest-dir`. | `/tmp` |
| `--retain N` | Keep the N most recent backups per source file. `0` disables. | 3 |
| `--dry-run` | Show what would happen without writing or deleting. | off |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Runtime error (I/O, compression, SHA mismatch) |
| 2 | Bad argument (source/restore path not a file) |
| 3 | Not inside a git repository (no default `--dest-dir` resolvable) |

## Examples

```bash
# Back up the current session jsonl (defaults everywhere)
jsonl_snapshot --source ~/.claude/projects/.../c84f8b1c-....jsonl

# Preview retention behaviour without writing or compressing
jsonl_snapshot --source <file> --dry-run --retain 3

# Restore to /tmp (default)
jsonl_snapshot --restore backup/sessions/raw/20260414T173000Z__c84f8b1c-....jsonl.gz

# Restore to a specific directory
jsonl_snapshot --restore <backup.gz> --target-dir /Volumes/External/recovery

# Run as a Python module
python -m jsonl_snapshot --source <file>
```

## See also

- [`session_snapshot`](../session_snapshot/README.md) — strategic-tier
  backup for Claude Code memory files (git-tracked, no sidecar, more
  frequent)
- `~/.claude/commands/snapshot.md` — the custom slash command that
  invokes `session_snapshot` on the current session's memory file
