# `hybrid_scripts_python` PR #4 — `compile_guides.py` Review Ask

**Date:** 2026-04-20 01:45 UTC
**PR:** [#4](https://github.com/abitofhelp/hybrid_scripts_python/pull/4)
**Branch:** `feat-compile-guides`
**Base:** `main` @ `cf36a0f`
**Scope:** New sibling script for compiling `docs/guides/*.typ` to PDF. Tooling-only; no existing behavior changed.

---

## Context

Ecosystem convention shift for developer guides: Markdown → Typst. Rationale: Typst handles tables + inline SVG better than Markdown, both key for technical guides. The shared guide template already landed in `shared_docs` (commit `61ba5c1`, `templates/guides/core.typ`).

This PR adds the compile script. The documentation agent (`~/.claude/agents/documentation.md`) was updated in the same session to specify `.typ` for guides with the new template. Consumer projects wire the script in via a new `docs-guides` Makefile target.

## What's in the PR

One new file: `makefile/compile_guides.py` (234 LOC).

Design is a close sibling of `compile_formal_docs.py`:

- Same temp-dir strategy: colocate shared template + project sources, run `typst compile`, write PDFs back to `docs/guides/`.
- Same `--project-dir` / `--templates-dir` / `--dry-run` flag shape.
- Targets `docs/guides/` and `~/shared_docs/templates/guides/` instead of `docs/formal/` and `~/shared_docs/templates/formal/`.

## Why sibling, not parameterize

Considered generalizing `compile_formal_docs.py` with a `--subdir` and `--templates-dir` flag pair. Rejected because:

- The formal script is already on 11 projects via the submodule, tested, working in CI. Generalizing carries breakage risk for formal-doc builds.
- The two doc classes have subtly different lifecycles: formal docs have a profile block and version/status lifecycle; guides don't. Keeping entry points separate makes the diff between "formal doc build" and "guide build" visible at the script level.
- If we later want to DRY shared logic, we can extract a common module without disrupting either entry point.

## Consumer wiring

Downstream projects add:

```makefile
docs-guides: ## Compile Typst developer guides to PDF
	@python3 scripts/python/shared/makefile/compile_guides.py
```

astfmt has already added this (plus an aggregate `docs` target that runs formal + guides). Waiting on this PR to merge + submodule pointer bump to land in the astfmt PR #92 branch.

## Verification

- Smoke-tested locally against astfmt's new `docs/guides/logger_setup.typ`:
  - `python3 compile_guides.py --project-dir /path/to/astfmt` → 1 succeeded, 0 failed; rendered a 122 KB PDF.
- `--dry-run` flag lists what would be compiled without running `typst`.
- Missing `typst` binary → clear error.
- Missing `docs/guides/` directory → clear error.
- Missing `--templates-dir` → clear error.

## Specific review asks

1. **Sibling vs generalization** — is the sibling-script call right for long-term ecosystem maintenance, or would you rather see a shared helper module that both `compile_formal_docs.py` and `compile_guides.py` import?
2. **Default templates dir** — hard-coded to `~/shared_docs/templates/guides`. Same pattern as the formal sibling. Acceptable?
3. **PDF output location** — written back to `docs/guides/` (alongside the `.typ` source), not a separate `build/` or `_out/` directory. Same as the formal sibling. The `.pdf` is typically committed so CI consumers don't need Typst installed. Confirm that shape?
4. **Any policy knob you'd add** — e.g., `--fail-on-warnings`? The script currently passes Typst's exit code through but doesn't escalate warnings.

## Out of scope

- Migration of existing `docs/guides/*.md` files in sibling projects (e.g., `hybrid_lib_ada` has four). Separate per-project exercise.
- A `compile_docs.py` umbrella script that invokes both siblings. Trivial to add later; left out to keep this PR focused.

---

If approved, I merge PR #4 → bump astfmt's submodule pointer on the PR #92 branch → land PR #92 → queue the `hybrid_lib_ada` guide migration for a separate session.
