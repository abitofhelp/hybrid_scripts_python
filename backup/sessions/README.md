# backup/sessions/

Durable, git-tracked archive of session artifacts for this repo.

## What lives here

Pre-phase asks, GPT direction-lock artifacts, PR-level review asks, and
time-driven session snapshots — all using the same filename convention
so chronological sort works across kinds:

```
<YYYYMMDDTHHMMSSZ>__<original-basename>
```

This matches the ecosystem convention established for the ~11 abitofhelp
consumer repos that mount `scripts/python/shared` (this repo).

## What this is NOT

- **Not the Claude Code `/export` command output.**
- **Not a full conversation transcript.** These are review artifacts
  and planning documents, not verbatim transcripts.

## Relationship to `backup/sessions/raw/`

`raw/` (if present) is gitignored and holds compressed full-session
`.jsonl` backups produced by `jsonl_snapshot/`. Those files are large
and intended for external storage. Git-tracked artifacts stay up here
in `backup/sessions/`.
