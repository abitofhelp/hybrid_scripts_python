# session_snapshot

One-sentence purpose: **back up a Claude Code memory file into the
current git repo's `backup/sessions/` directory with SHA-256
verification and per-source retention.**

Paired with [`jsonl_snapshot`](../jsonl_snapshot/README.md), which does
the same job for full conversation jsonls (the forensic tier).

---

## When to use

- **Preferred**: via the `/snapshot` custom slash command (defined in
  `~/.claude/commands/snapshot.md`), which calls this script on the
  current session's memory file. That matches the "save this moment in
  time" workflow the old `/export` command used to provide.
- **Directly from the CLI** for scripting, testing, or ad-hoc
  snapshots outside Claude Code.

## What it backs up

Claude Code memory files, typically written by the assistant at
`~/.claude/projects/<encoded-project-path>/memory/*.md`. These are
not git-tracked by Claude Code itself, so a local-state loss (disk
failure, accidental delete, corruption) destroys them unless they
have been mirrored somewhere durable.

## Where backups land

Default: `<git-root>/backup/sessions/` of the current project, where
`<git-root>` is resolved via `git rev-parse --show-toplevel` from the
caller's working directory. The target directory is git-tracked, so
once the snapshot is committed and pushed the backup is durable on
GitHub (or whichever origin you push to).

Override with `--dest-dir`.

## Filename convention

```
<YYYYMMDDTHHMMSSZ>__<original-basename>
```

- UTC ISO 8601 compact timestamp, so chronological sort is unambiguous
  across time zones and across machines.
- Double underscore `__` separator between the timestamp prefix and
  the preserved original filename.
- The original filename is kept verbatim after the separator, which
  makes recovery a one-liner (strip `<timestamp>__`, `cp` back).

Same-UTC-second collisions (rare — only under automated testing or
very rapid invocations) get a `.N` disambiguator:

```
20260414T173000Z__project_session_20260414_b1i_b.md     (first)
20260414T173000Z.1__project_session_20260414_b1i_b.md   (second)
```

Chronological sort still works because the disambiguator is part of
the prefix.

## SHA-256 verification

Every snapshot hashes the source, copies, then hashes the destination.
A mismatch causes the script to **remove the partial destination and
exit non-zero**. There is no silent corruption path.

No sidecar `.sha256` file is written for memory-file snapshots because
the backup destination is git-tracked. Git's own blob store is
SHA-based content-addressed storage — once committed, the file's
integrity is cryptographically guaranteed by git itself, and a sidecar
would be dead code. (The sibling `jsonl_snapshot` tool *does* write a
sidecar because its destination is gitignored.)

## Retention

Per-source-file grouping, default `--retain 5`. Group key is the
original basename (everything after `<timestamp>__`). When the group
exceeds the retention count after a new backup lands, the **single
oldest** file in that group is deleted. At most one purge per
invocation, ever — this bounds the blast radius of any retention bug
and forces convergence to happen over multiple runs rather than in one
big delete.

`--retain 0` disables retention entirely.

Event-driven files that appear once (alignment notes, PR review
packages) are never purged by heavy activity on a different source
file, because grouping is by basename rather than by directory.

## Recovery

### Option 1: `--restore` mode (recommended)

```
session_snapshot --restore backup/sessions/20260414T173000Z__project_session_20260414_b1i_b.md \
                 --target-dir ~/.claude/projects/<encoded>/memory/
```

The script strips the `<timestamp>__` prefix, copies the backup into
`--target-dir` with the original filename, and SHA-256 verifies the
restored file before returning. If `--target-dir` is omitted, the
restore target defaults to the backup file's own directory (safe
no-op when you just want to sanity-check the backup).

### Option 2: plain `cp`

```
cp backup/sessions/20260414T173000Z__project_session_20260414_b1i_b.md \
   ~/.claude/projects/<encoded>/memory/project_session_20260414_b1i_b.md
```

Strip everything up to and including `__` and you have the original
filename. The prefix is there exactly so this works.

### After restore

Start a new Claude Code session. The Claude Code auto-memory system
reads `~/.claude/projects/<encoded>/memory/*.md` at session start, so
the restored file is picked up automatically. Anything that happened
between the snapshot and the corruption is reconstructed from git
history, the current conversation, and your own memory.

## CLI reference

```
session_snapshot [--source FILE | --restore FILE]
                 [--dest-dir DIR]
                 [--target-dir DIR]
                 [--retain N]
                 [--dry-run]
```

Flags:

| Flag | Purpose | Default |
|---|---|---|
| `--source FILE` | Back up this file. Mutually exclusive with `--restore`. | — |
| `--restore FILE` | Restore this backup to its original filename. Mutually exclusive with `--source`. | — |
| `--dest-dir DIR` | Destination for `--source`. | `<git-root>/backup/sessions/` |
| `--target-dir DIR` | Destination for `--restore`. Alias for `--dest-dir`. | backup's own directory |
| `--retain N` | Keep the N most recent backups per source file. `0` disables retention. | 5 |
| `--dry-run` | Show what would happen without writing or deleting. | off |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Runtime error (I/O failure, bad filename pattern, SHA mismatch) |
| 2 | Bad argument (source/restore path not a file) |
| 3 | Not inside a git repository (no default `--dest-dir` resolvable) |

## Examples

```bash
# Back up a memory file with everything defaulted
session_snapshot --source ~/.claude/projects/.../memory/project_session_20260414_b1i_b.md

# Preview retention behaviour without writing anything
session_snapshot --source <file> --dry-run --retain 3

# Restore a backup to its original location
session_snapshot --restore backup/sessions/20260414T173000Z__project_session_20260414_b1i_b.md \
                 --target-dir ~/.claude/projects/.../memory/

# Run as a Python module
python -m session_snapshot --source <file>
```

## See also

- [`jsonl_snapshot`](../jsonl_snapshot/README.md) — forensic-tier
  backup for full Claude Code session jsonls (compressed, with
  dual-hash sidecar, gitignored target)
- `~/.claude/commands/snapshot.md` — the custom slash command that
  invokes this tool on the current session's memory file
