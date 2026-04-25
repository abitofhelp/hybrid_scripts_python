# PR Review Ask — `coverage_ada.py` `GPRBUILD_EXTRA_ARGS` plumbing

**Branch**: `add-gprbuild-extra-args`
**Base**: `main` @ `b55ad6d`
**Kind**: Small follow-up to PR #7. Generic per-consumer scenario-flag plumbing for the shared coverage script.
**Triggered by**: astfmt's D-062 retirement attempt — Step 3 instrumented `gprbuild` failed with `cannot find -liconv` because astfmt's normal build uses `-XGNATCOLL_ICONV_OPT=` (glibc-Linux iconv-disable scenario var) and the shared script wasn't propagating any equivalent.

## What changed

- New `gprbuild_extra_args()` helper reads `GPRBUILD_EXTRA_ARGS` from the environment and shell-tokenises it via `shlex.split(...)`.
- Applied at the **two `gprbuild` invocation sites** that consumers' build flags affect:
  - Step 1 legacy `gprbuild` (v22 fallback runtime build)
  - Step 3 instrumented test `gprbuild` (both unit and integration)
- **NOT applied** to `gnatcov setup` (v26+; not gprbuild), `gnatcov instrument`, or `gnatcov coverage`.

Per owner direction:

> astfmt's iconv flag is per-project build policy. It belongs in astfmt's Makefile target, not the shared script. The shared script should expose a generic mechanism and stay project-agnostic.

## Why a separate PR

Issue #5 was closed by PR #7 (gnatcov 26 setup compatibility). The iconv linker error surfaced when applying that PR to the real astfmt consumer. Bundling this fix into a hypothetical "PR #7 amendment" would have muddied the v26/v22 dispatch story; splitting it into a targeted "extra-args plumbing" PR keeps each cycle's diff focused and reviewable in isolation. The astfmt-side D-062 retirement (which depends on this PR) is the third PR in the chain.

## Tests

5 new pytest cases in `tests/test_coverage_ada_extra_args.py`:
- Returns `[]` when env var unset.
- Returns `[]` on blank/whitespace-only value (regression pin: `shlex.split('')` returning `[]`).
- Single flag (`-XGNATCOLL_ICONV_OPT=`) round-trips intact.
- Multiple space-separated flags split correctly.
- Quoted values with embedded spaces stay a single token.

Full pytest suite: **41/41** passing (5 new + 36 prior).

## Consumer wiring (astfmt-side, applied in the next PR)

```make
test-coverage:
	@GPRBUILD_EXTRA_ARGS="-XGNATCOLL_ICONV_OPT=" \
	  $(PYTHON3) scripts/python/shared/makefile/coverage_ada.py
```

That single line is what the chain needs astfmt-side. Other consumers may pass their own scenario flags (e.g. `-XLIBRARY_TYPE=static` or `-XBUILD_PROFILE=...`) the same way.

## Review asks for GPT

1. **Application sites** — applied at legacy Step 1 `gprbuild` + Step 3 `gprbuild` (unit + integration), per the owner's directive: "Apply it to legacy Step 1 gprbuild + Step 3 instrumented test gprbuild. Do NOT apply it to gnatcov setup or gnatcov instrument." Coverage matches your direction?

2. **`shlex.split` for tokenisation** — single-flag and quoted-multi-flag values round-trip correctly. Right tool, or do you prefer a more conservative `str.split()` (which would reject quoted-string semantics)?

3. **Helper visibility** — `gprbuild_extra_args()` is a module-level public function; the docstring explicitly enumerates the application sites and the not-applied list, so future contributors don't accidentally extend coverage to `gnatcov instrument`. Right place to lock that contract, or do you prefer a more rigid mechanism (e.g. an explicit allowlist of phases)?

4. **Test coverage** — five cases covering unset / blank / single / multi-flag / quoted-value. Sufficient, or do you want a negative-path test (e.g. unbalanced quotes raising `ValueError` from `shlex.split`)?

5. **Anything missed** before merge? Patch is deliberately minimal; the value lives in being a tiny, separate PR rather than getting bundled.

## Scope discipline (NOT done)

- **No** Ada source change anywhere
- **No** consumer rollout (astfmt-side wiring is the next PR)
- **No** Step 2 / Step 4 / Step 5 change
- **No** `gnatcov instrument` / `gnatcov coverage` / `gnatcov setup` change

## My merge disposition leaning

**Approve.** The patch is deliberately small (one helper + two `+ extra_args` insertions) and the test suite provides the contract that future regressions need to clear. PR #7's strawman E2E remains valid since `GPRBUILD_EXTRA_ARGS` defaults to empty.

## References

- Issue #5 + PR #7 (gnatcov 26 compatibility — the parent)
- astfmt D-062 (the §8.b waiver retirement that this PR unblocks)
