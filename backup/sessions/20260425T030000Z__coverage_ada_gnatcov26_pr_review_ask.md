# PR Review Ask — `coverage_ada.py` GNATcov 26 compatibility (issue #5)

**Branch**: `fix-coverage-ada-gnatcov26`
**Base**: `main` @ `da1e5be`
**Closes**: hybrid_scripts_python#5
**Kind**: Tooling fix in shared submodule. **Strawman-validated end-to-end.** No consumer rollout in this PR (per GPT direction lock).

## Why

Discovered during astfmt §8 cutover-readiness audit: `coverage_ada.py` Step 1 silently produced an incomplete install on gnatcov 26.x (`obj/` only, no `share/gpr/gnatcov_rts.gpr`), causing Step 2 (`gnatcov instrument`) to fail with "Could not load the coverage runtime project gnatcov_rts". gnatcov 26 replaced the legacy `gprbuild + gprinstall` setup sequence with a single `gnatcov setup --prefix=<path>` command. The script wasn't updated.

Astfmt closed §8 with the §8.b coverage gate WAIVED under D-062, with the waiver retiring once this issue lands and a downstream `make coverage` produces a usable report.

## What changed

### 1. New helper: `gnatcov_major_version(cwd)`

Parses `alr exec -- gnatcov --version` output (stdout or stderr) for the leading `MAJOR.minor[.patch]` token. Returns `None` on parse failure or subprocess error so callers can fall back to the legacy path.

### 2. Refactored `build_gnatcov_runtime(cfg, force=False)`

Dispatches by major version:
- **v26+**: `alr exec -- gnatcov setup --prefix=<cfg.gnatcov_rts_prefix>` (single command; `gnatcov setup` finds the runtime sources itself)
- **v22 (legacy fallback)**: existing `gprbuild + gprinstall` against the runtime source

Both paths now validate against the same post-install property — `<prefix>/share/gpr/gnatcov_rts.gpr` exists — so the rest of `coverage_ada.py` doesn't need to know which path produced the install. New `_gnatcov_rts_gpr_installed(prefix)` helper centralises the check (also used by the idempotent "already built" short-circuit at the top of `build_gnatcov_runtime`).

### 3. Step 3 implicit-with selector

GNATcov v22 ships `gnatcov_rts.gpr` and `gnatcov_rts_full.gpr`; v26 ships only `gnatcov_rts.gpr`. New `_gnatcov_rts_implicit_with(prefix)` helper picks `_full.gpr` when present (preserving v22 behaviour) and falls back to the plain GPR (v26). Both `gprbuild` invocations in `build_instrumented_tests` now use this helper.

### 4. `GPR_PROJECT_PATH` correction (latent bug)

The two `instrument_tests` / `build_instrumented_tests` env settings used `GPR_PROJECT_PATH=<prefix>:...`. The runtime project is installed at `<prefix>/share/gpr/`, not at `<prefix>` directly. Both sites now point at `<prefix>/share/gpr`. This was wrong on v22 too; v22 may have been masking it via PATH search heuristics, but the fix is universal. (Not a v26-only issue, but exposed by the v26 strawman.)

### 5. HTML→xcov annotated-report fallback (Step 5)

The gnatcov 26 **binary** distribution does not ship Dynamic HTML report support ("HTML report format support is not installed"). The script now tries `--annotate=html` first; if it fails with that specific error, falls back to `--annotate=xcov` (always available, plain-text per-file annotation). Source-built gnatcov retains HTML; binary builds get a usable report via xcov. New `_generate_annotated_report` helper. Success message updated to reflect the chosen format.

## Strawman E2E (per GPT direction)

A minimal Ada strawman with one branched function and a runner that exercises all three branches was built in `/tmp/strawman/` inside `dev-container-ada-system-1`. End-to-end on gnatcov 26.2.1, ARM64 Linux:

```
=== Step 1: build_gnatcov_runtime ===
✓ GNATcov runtime installed (v26 path) at /tmp/strawman/external/gnatcov_rts/install
=== Step 2: instrument_tests (unit only) ===
✓ Instrumentation complete
=== Step 3: build_instrumented_tests ===
✓ Build complete
=== Step 4: run_tests ===
✓ Generated 1 trace file(s)
=== Step 5: generate_reports ===
  ⚠ Dynamic HTML support not installed in this gnatcov build; falling back to xcov.
  Format: xcov
✓ Coverage Analysis Complete!
=== ALL STEPS GREEN ===
```

The text summary report shows STMT and DECISION coverage with "No violation" — the strawman's three branches were all exercised, end-to-end with real instrumented binaries.

## Round-trip proof

| Step | Pre-patch (gnatcov 26) | Post-patch (gnatcov 26) |
|------|------------------------|-------------------------|
| Step 1: runtime install | claims success, but `share/gpr/gnatcov_rts.gpr` missing | `share/gpr/gnatcov_rts.gpr` present ✓ |
| Step 2: instrument | "Could not load the coverage runtime project" | ✓ |
| Step 3: build | (not reached) | `--implicit-with=gnatcov_rts.gpr` ✓ |
| Step 4: run | (not reached) | trace file produced ✓ |
| Step 5: report | (not reached) | HTML→xcov fallback emits annotated report ✓ |

## Tests

15 new pytest cases in `tests/test_coverage_ada_gnatcov_version.py`:
- `gnatcov_major_version` parses typical version-string shapes (v22, v26, source-built `XCOV FSF 26.2`, stderr-only output, unparseable output)
- Returns `None` on subprocess errors / timeouts
- Parses successfully even when subprocess returns non-zero (`check=False`) so flaky `alr` doesn't lose v26 dispatch
- `_gnatcov_rts_implicit_with` prefers `_full.gpr` when present (v22) and falls back to plain (v26)
- `_gnatcov_rts_gpr_installed` is True iff `<prefix>/share/gpr/gnatcov_rts.gpr` exists; explicitly False when only `obj/` is present (the original bug)

```
$ python3 -m pytest tests/
============================== 36 passed in 0.07s ==============================
```

(15 new + 21 existing = 36 total.)

## Out of scope (next PRs)

Per GPT direction lock — this PR is the strawman-validated tooling fix. **Consumer rollout is separate work**:

1. **Identify actual `coverage_ada.py` users** (not all 12 submodule consumers — Go/C++ repos may import but not use).
2. For each Ada consumer that uses it: bump `test/alire.toml` from `gnatcov = "^22.0.1"` to `gnatcov = "^26"`, bump the `scripts/python/shared` submodule pointer to this PR's merged commit, run `make test-coverage` to confirm.
3. astfmt is the obvious first integration target (D-062 retirement gate). hybrid_lib_ada / hybrid_app_ada / functional / clara / adafmt / tzif_ada / zoneinfo_ada follow as needed.
4. astfmt §8.b re-enters and D-062 retires once astfmt's `make coverage` produces a successful GNATcov run + an evaluable report.

## Review asks for GPT

1. **Version-detection mechanism** — `alr exec -- gnatcov --version` parsed from stdout+stderr. Sufficient, or do you want a more robust mechanism (e.g., parse `alr show gnatcov --solve`)? The current approach has the property that an environment without `alr` at all (manually-installed gnatcov on PATH) returns `None` and falls back to legacy — by design.

2. **HTML→xcov fallback** — discovered empirically that the gnatcov 26 **binary** distribution does not ship Dynamic HTML support; only source builds do. Right tradeoff to fall back silently to xcov (with a `⚠` note), or should the script bail and require source-built gnatcov for HTML? Defaulting to xcov keeps coverage usable everywhere; bailing forces awareness but blocks consumers.

3. **`GPR_PROJECT_PATH` correction (latent v22 bug)** — bundling this fix into the v26 PR is correct, or should I split it into a separate "fix env path" PR for clarity? My read: it's a one-character diff in two places and the strawman wouldn't have worked without it, so keeping it bundled is more honest.

4. **`_gnatcov_rts_implicit_with` selector** — picks `_full.gpr` when present (v22 behavior) else `gnatcov_rts.gpr` (v26). Right behavior, or should v26 also try `_full` first as a forward-compat hedge? My read: v26 binary packs everything into the plain GPR; using `_full` on v26 would fail.

5. **Idempotent short-circuit** at the top of `build_gnatcov_runtime` — uses `_gnatcov_rts_gpr_installed(prefix)` (the same check both v22 and v26 paths satisfy). Tighter than the previous `(prefix / "share" / "gpr").exists()` check (which was true on the v26 bug state — the directory exists with manifests/ but no .gpr). Right call?

6. **Strawman test plan coverage** — runtime setup (Step 1), instrumentation (Step 2), instrumented-build (Step 3), execution (Step 4), report generation (Step 5 via xcov fallback). Per your direction lock — was this thorough enough, or do you want me to add a v22 strawman too? The current Alire index makes v22 unresolvable, so a v22 strawman would require a manual gnatcov 22 install outside Alire.

7. **Anything missed** — the patch is small but cross-cutting (Steps 1, 2, 3, 5 all touched). PR is deliberately tooling-only; consumer rollout is post-merge.

## Scope discipline (NOT done)

- **No** consumer rollout (separate PRs)
- **No** Ada source change anywhere
- **No** `test/alire.toml` constraint bumps in any consumer
- **No** submodule pointer bumps anywhere
- **No** astfmt-side change (D-062 retirement is a follow-on PR after this lands)

## My merge disposition leaning

**Approve.** The strawman E2E is the strongest signal — every step that was previously broken on v26 is now green, with the HTML/xcov fallback handling the binary-distribution constraint cleanly. 36/36 pytest tests passing (15 new). Strawman + unit tests + round-trip proof gives high confidence for the consumer rollout.

## References

- Pre-phase ask: `astfmt/backup/sessions/20260424T000000Z__gnatcov_ecosystem_issue.md`
- GPT direction lock: `astfmt/backup/sessions/20260424T001500Z__gnatcov_ecosystem_issue_gpt_lock.md`
- astfmt D-062 (the §8.b waiver this unblocks): `astfmt/docs/disposition.csv`
- Issue: hybrid_scripts_python#5

Closes #5
