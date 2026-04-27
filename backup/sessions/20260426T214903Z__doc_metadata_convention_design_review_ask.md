# Pre-Implementation Design Review — Document Metadata Convention v2

**Date**: 2026-04-26
**Status**: Pre-phase, no code written yet
**Decision required before**: any edits to `release/`, `brand_project/`, or document files

## Context

Across the abitofhelp ecosystem (functional, astengine, astfmt, adafmt, hybrid_lib_*, hybrid_app_*, etc.) we are standardizing on a new document cover-page convention that decouples doc revision from library version. The current convention conflates them with a single `**Version:**` field.

The change affects:

1. The Documentation agent file at `~/.claude/agents/documentation.md` (canonical authoring authority — already updated; pending GPT sign-off).
2. The shared Typst cores at `~/shared_docs/templates/{formal,guides}/core.typ` (rendering layer for all `.typ` docs).
3. **`release/adapters/base.py`** — release-time metadata sync that today writes the OLD form everywhere.
4. **`brand_project/adapters/base.py`** — project scaffolding that today seeds the OLD form into new projects.

Without redesigning #3 and #4 in the same change, the next release run on a migrated repo would silently overwrite the new convention with the old form.

## New convention (Markdown form)

```markdown
# Document Title

**Doc Version:** X.Y.Z<br>
**Applies to <project>:** ^A.B<br>
**Last Updated:** YYYY-MM-DD<br>
**SPDX-License-Identifier:** BSD-3-Clause<br>
**License File:** See the LICENSE file in the project root<br>
**Copyright:** © YYYY Michael Gardner, A Bit of Help, Inc.<br>
**Status:** [Draft|In Progress|Released]
```

Three changes vs. the current convention:

- `**Version:**` → `**Doc Version:**` (clarify — was ambiguous)
- `**Date:**` → `**Last Updated:**` (clarify)
- ADD `**Applies to <project>:**` (lock the doc to a code-version range)

License/Copyright/Status fields are unchanged. Source-code headers (`pragma Ada_2022; -- ... -- SPDX-License-Identifier: ...`) are NOT affected — they don't have Version/Date fields and never should.

## Proposed field-ownership split

| Field | Owner | Release-script behavior |
|-------|-------|------------------------|
| **Doc Version** | Doc author | **Read-preserve**: parse existing value from the file, write back unchanged. Doc author bumps it when they edit; releases never overwrite it. |
| **Applies to <project>** | Release process | Always write `^{major}.{minor}` derived from `config.version`. Mechanical, not opinion. Releasing 1.0.0 sets `^1.0`; releasing 2.0.0 bumps to `^2.0`. |
| **Last Updated** | Release process | Always overwrite with today's date. |
| **SPDX-License-Identifier** | Standard | Always emit `BSD-3-Clause`. |
| **License File** | Standard | Always emit standard text. |
| **Copyright** | Standard | Always emit current year. |
| **Status** | Release process | Released or Unreleased per `is_prerelease`. |

**Rationale**:

- Doc Version is doc-author-owned because the entire reason for splitting it from library version is "doc-only fixes don't require a code release." If the release script overwrites it, that decoupling is fictional.
- Applies to is release-owned because it's a compatibility statement about the just-shipped library — the doc author shouldn't have to remember to update it manually.
- Last Updated is release-owned because the release run physically touches the file (Status, Applies to). If we want it to mean "last edited by a human," it would have to be doc-author-owned, but then it goes stale every time release rewrites the file. Cleaner to define it as "release-touched date."

## Lenient detection / strict emission

Confirmed by owner:

- **Detection** accepts both old and new forms (`^\*\*(?:Doc )?Version:`, plus `Date|Last Updated`, etc.).
- **Emission** always writes the new convention.

A release run on a not-yet-migrated repo correctly identifies its docs and rewrites them into the new form. After all repos have been swept, detection can tighten to new-form-only as a separate cleanup.

## Migration cost

When the script encounters an OLD-form doc, it has no Doc Version field to preserve (the old `Version:` is library version, not doc version). The rewrite will reset Doc Version to `config.version` (the library version being released). This is one-time migration cost — after the first post-convention release, every doc has an independent Doc Version that the script will preserve from then on.

Acceptable, IMO — there's no way to invent an independent Doc Version retroactively, and aligning with library version at the migration moment is the cleanest entry into the new model.

## Scaffolding default (`add_markdown_header` and brand_project)

When the script scaffolds a header into a doc that lacks one entirely, it must choose a Doc Version starting value:

- **(a) Use `config.version` (the library version being released)** — proposed default. Doc starts synchronized with the first release; doc author bumps independently afterwards.
- (b) Always `0.1.0` — fresh doc, mark as pre-stability.
- (c) Context-aware: `1.0.0` if `is_initial_release`, else `0.1.0`.

`brand_project` scaffolding (new project being created from the brand template) always uses fixed defaults:

- Doc Version: `0.1.0`
- Applies to <project>: `^0.1`
- Last Updated: today
- Status: Draft

This is correct because a freshly branded project is always pre-1.0 by definition.

## Implementation plan (one PR against hybrid_scripts_python)

1. `release/models.py` — add `applies_to_range: str` field, computed in `__post_init__` from `version` as `^{major}.{minor}`.
2. `release/adapters/base.py`:
   - `find_markdown_files` regex (line 289): widen to accept old + new forms.
   - `replace_markdown_header` (line 298): parse + preserve existing `Doc Version`; emit new convention; write `Applies to` mechanically.
   - `add_markdown_header` (line 352): emit new convention with `Doc Version: {config.version}`.
   - Header-existence sniff at line 372: extend regex to include `Doc Version|Applies to|Last Updated`.
3. `brand_project/adapters/base.py` (lines 455-456): emit new convention with scaffolding defaults above.
4. Add tests covering: (a) old-form doc gets migrated correctly, (b) new-form doc has Doc Version preserved across release runs, (c) doc with no header gets new-convention scaffolding.

Separately (different repo, separate PR):

- `~/shared_docs/templates/formal/core.typ` and `~/shared_docs/templates/guides/core.typ` — rename row labels, add `applies_to` field rendering.

## Specific review asks (please answer one-by-one)

**Q1.** Is the field-ownership split (Doc Version doc-author-owned, Applies to release-owned, Last Updated release-owned) the right boundary, or would you split it differently? Specifically, is `Last Updated` defensible as release-owned, or should it be doc-author-owned with a separate `Last Released:` field?

**Q2.** Is `Doc Version: {config.version}` the right default for the `add_markdown_header` scaffolding case, or should it be `0.1.0`? The trade-off: (a) "doc starts synced with first release" vs. (b) "doc always starts at pre-1.0 to make the bump-decision explicit when first releasing."

**Q3.** Is "Applies to is release-owned, mechanically computed as `^{major}.{minor}`" the right approach? The alternative is making it doc-author-owned with the doc author manually setting compat ranges. The release-owned approach assumes the doc never explicitly supports a narrower range than the latest release; is that ever wrong?

**Q4.** Is anything missing from the lenient-detection regex set? Today the existing regex is:

```python
r'Version\s*[:)]|version\s*[:)]|\*\*Version\s+\d+\.\d+|Copyright\s*©\s*\d{4}'
```

The proposed widened version would need to also match `**Doc Version:`, `**Last Updated:`, `**Applies to`. Any other old-form patterns we'd lose detection on?

**Q5.** Migration-time cost: the rewrite resets Doc Version to library version on first migration of an old-form doc. Is that acceptable or would you prefer a more gradual mode (e.g., a `--migrate-headers` flag that's an explicit one-off, separate from regular release runs)?

**Q6.** Do you see any other conflict surfaces in the ecosystem we should scan before touching code? (Already scanned: `~/.claude/CLAUDE.md` — no conflicts. Other agents `ada.md`/`cpp.md`/`python.md` — use the convention in their own headers as self-examples, marginal call. Source-code headers — confirmed no overlap.)

**Q7.** Should the existing release-script behavior of touching ALL markdown files (`docs/**/*.md`, `*.md`, `config/*.md`) stay as-is, or should the new convention be enforced more conservatively (e.g., opt-in via a `.docmetadata.toml` file in the project root)?
