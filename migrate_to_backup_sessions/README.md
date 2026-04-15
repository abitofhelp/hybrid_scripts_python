# migrate_to_backup_sessions

One-sentence purpose: **idempotent rollout helper that brings a
consumer project into conformance with the `backup/sessions/`
convention defined by `session_snapshot` and `jsonl_snapshot`.**

---

## When to use

- **Once per consumer project** during the initial rollout of the
  backup/sessions convention.
- **Anytime later** to re-check a project against the convention —
  the tool is idempotent, so rerunning it on a conforming project
  is a safe no-op that reports "nothing to do".
- **After a convention change** — if the target state evolves, a
  new release of this tool can bring every consumer back into
  conformance with one command per repo.

This tool is the paired migration helper for the two snapshot
tools. See
[`session_snapshot`](../session_snapshot/README.md) and
[`jsonl_snapshot`](../jsonl_snapshot/README.md) for the backup
tools themselves.

## What it does

Given a consumer project git repository, the tool:

1. **Creates `backup/sessions/`** if missing.
2. **Writes `backup/sessions/README.md`** from an embedded template
   that documents the convention (project-agnostic, no name
   substitution needed).
3. **Writes `backup/sessions/raw/.gitignore`** so the `raw/`
   subdirectory is tracked but its contents are ignored.
4. **Adds `exports/` to the project's root `.gitignore`** with an
   explanatory comment block. Skipped if `exports/` is already
   ignored.
5. **Removes tracked 0-byte `exports/*` files** via `git rm`. These
   are stubs created by the broken Claude Code `/export` command
   and have no content.
6. **Bumps the `scripts/python/shared` submodule pointer** to the
   target SHA (default: `hybrid_scripts_python` main HEAD at the
   time this tool shipped). Overridable via `--submodule-ref`.
7. **Lists non-zero-byte `.md` files in `exports/`** as
   **candidates** for human review. These are NOT migrated by
   default because judgment is required: some are meaningful
   alignment notes or PR review packages worth preserving, others
   are stale scratch that should just be dropped.

Optional mode:

- **`--migrate-all-md`**: also `git mv` every candidate into
  `backup/sessions/` with a UTC-prefixed name derived from the
  candidate's first-commit timestamp. Use this when you want to
  preserve everything and cherry-pick drops afterward.

The tool **never commits**. All changes are left staged in the
working tree so the operator can review and commit them as a
single migration commit.

## Idempotency

Every task checks its target before acting:

- Directory creation is `mkdir -p`, harmless if already present.
- File writes use "write if missing" semantics.
- `.gitignore` appending checks for the sentinel line first.
- Submodule pointer is compared against the target SHA before
  calling `git submodule update --remote`.
- Zero-byte stub removal walks tracked files and only touches
  files with `stat().st_size == 0`.

A consumer project that has already been migrated reports
"nothing to do" on a rerun. A partially migrated project gets
only the missing pieces applied.

## Filename convention for migrated `.md` files

Matches `session_snapshot` and `jsonl_snapshot`:

```
<YYYYMMDDTHHMMSSZ>__<original-basename>
```

The UTC timestamp comes from `git log --diff-filter=A --follow` on
the candidate file — it is the first commit that added the file to
the index. Authoritative, unambiguous, and matches the timestamp
strategy used elsewhere.

Candidates whose first-commit timestamp cannot be resolved (never
committed, path outside the repo, git history rewritten) are
**skipped** even in `--migrate-all-md` mode, with an explicit
"skipped: cannot derive UTC timestamp" message. Those files must
be moved manually.

## CLI reference

```
migrate_to_backup_sessions [--project-root DIR]
                           [--submodule-ref SHA]
                           [--migrate-all-md]
                           [--dry-run]
```

| Flag | Purpose | Default |
|---|---|---|
| `--project-root DIR` | Consumer project git root. | `find_git_root(cwd)` |
| `--submodule-ref SHA` | Target SHA for `scripts/python/shared`. | `hybrid_scripts_python` main HEAD at tool ship time (see `DEFAULT_SUBMODULE_REF` constant) |
| `--migrate-all-md` | Also `git mv` every non-zero-byte candidate `.md`. | off |
| `--dry-run` | Report what would happen without writing. | off |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success (either "nothing to do" or changes applied) |
| 1 | Runtime error (I/O, git subprocess failure, value error) |
| 2 | Bad argument (invalid `--project-root`) |
| 3 | Not inside a git repository (no `--project-root` resolvable) |

## Typical workflow

```bash
# Start in a consumer project worktree
cd ~/Ada/github.com/abitofhelp/adafmt

# First pass: dry-run to see what will happen
PYTHONPATH=scripts/python/shared python3 -m migrate_to_backup_sessions --dry-run

# Second pass: apply the mechanical changes
PYTHONPATH=scripts/python/shared python3 -m migrate_to_backup_sessions

# Review the candidate list (printed at the end of the output):
#   - Keep the meaningful ones? Rerun with --migrate-all-md
#   - Drop everything? git rm the candidates manually
#
# In this example we keep everything:
PYTHONPATH=scripts/python/shared python3 -m migrate_to_backup_sessions --migrate-all-md

# Review staged changes and commit
git status
git diff --cached
git commit -m "chore(backup): adopt backup/sessions/ convention"
git push
```

Rerunning on a conforming project:

```bash
$ migrate_to_backup_sessions
project root:    /Users/mike/Ada/github.com/abitofhelp/adafmt
target submodule: a3ace7031203

already done:
  - backup/sessions/ exists
  - backup/sessions/README.md exists
  - backup/sessions/raw/.gitignore exists
  - exports/ already in .gitignore
  - scripts/python/shared submodule already at a3ace70

planned tasks: none (project already conforms)

non-zero-byte .md candidates: none

nothing to do; project already conforms.
```

## What this tool does NOT do

- **Does not commit.** Changes are staged and left for human review.
- **Does not push or open PRs.** That remains a manual step per
  project so the operator can add project-specific commit message
  content.
- **Does not touch the formal docs, disposition ledger, or any
  Ada/Go/C++ source code.** Migration scope is purely the
  operational directory layout and the submodule pointer.
- **Does not migrate non-`.md` files from `exports/`**, even if
  they have content. The candidate list only considers `.md`
  extensions because that matches the kind of meaningful artifacts
  the backup convention preserves. Other exports/ content
  (`.txt` with non-zero bytes, binaries, etc.) stays in place and
  will become untracked once `exports/` is in `.gitignore`.

## See also

- [`session_snapshot`](../session_snapshot/README.md) — strategic
  memory-file backup tool
- [`jsonl_snapshot`](../jsonl_snapshot/README.md) — forensic
  session-jsonl backup tool
- `backup/sessions/README.md` in any migrated consumer — same
  convention documentation, embedded by this tool during rollout
