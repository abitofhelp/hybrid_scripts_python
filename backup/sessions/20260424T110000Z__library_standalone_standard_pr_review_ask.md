# PR Review Ask — PR #6 (Library_Standalone="standard" Enforcement)

**PR**: https://github.com/abitofhelp/hybrid_scripts_python/pull/6
**Branch**: `library-standalone-root-gpr-enforcement` @ `ba90484`
**Base**: `origin/main` @ `2d5f401`
**Kind**: Tooling — production-code bug fix (template regen vector) + arch_guard enforcement extension + pytest tests.
**Position**: PR 1 of 3-repo rollout. **Must merge first.**

## Pre-merge discipline

- Pre-phase ask: `backup/sessions/20260424T100000Z__library_standalone_standard_prephase_ask.md`
- GPT direction-lock: `backup/sessions/20260424T101000Z__library_standalone_standard_gpt_direction_lock.md`
- This review ask: `backup/sessions/20260424T110000Z__library_standalone_standard_pr_review_ask.md`
- This PR is the **code review round**. Direction lock is complete; GPT's remaining scrutiny is on regex correctness, edge cases, test coverage rigor, and failure-message precision (per GPT's own final sign-off).

## Matches-locked-scope check

| Locked item | Implemented |
|---|---|
| Remove `standard → encapsulated` upgrade in `namespace_layers.py` | ✓ replaced block with an explanatory comment crediting `Library_Interface` for public-API enforcement |
| Extend arch_guard Ada adapter to validate root GPR | ✓ new `find_root_gpr` + `_validate_root_gpr` helpers + `validate_config` composition |
| Require `Library_Standalone use "standard"` on root | ✓ |
| Reject `Library_Standalone use "encapsulated"` on root | ✓ with canonical error text |
| Require `Library_Interface use (...)` on root (rule coupling) | ✓ |
| Canonical error message as shared constant | ✓ `ROOT_GPR_ENCAPSULATED_ERROR` exported from `arch_guard.adapters.ada` |
| Tests co-located at `tests/` (option (a)) | ✓ `tests/test_arch_guard_root_gpr.py` + `tests/fixtures/` + `tests/conftest.py` |
| 4 GPR fixtures — valid + 3 negatives | ✓ valid_root_standard / invalid_root_encapsulated / invalid_root_standard_no_interface + inline no-Library_Standalone + absent-GPR in-test |
| 11 pytest cases, all green | ✓ `python3 -m pytest tests/` — 11 passed in 0.02s |
| CHANGELOG entry (GPT ready-to-use text) | ✓ Keep-a-Changelog under `[Unreleased] → Changed` with migration note |
| Adopt `backup/sessions/` convention (repo hygiene) | ✓ 3 artifacts committed (pre-phase + direction lock + this review ask) |
| Root GPR detection fallback (GPT round-5 micro-improvement) | ✓ `find_root_gpr` tries `<name>.gpr` first, falls back to first non-internal `*.gpr` at root |
| Strengthened grep (`Library_Standalone.*encapsulated`) for verification | ✓ run manually; only intended matches remain |
| No consumer-repo changes | ✓ hybrid_lib_ada / astengine / astfmt untouched |
| No `feat-compile-guides` interaction | ✓ branched from `origin/main`, not from that feature branch |

## Actual shapes

### Canonical error string (API contract — treat as stable)

```
❌ Root GPR <gpr>: Library_Standalone = "encapsulated"

Required:
  Library_Standalone use "standard";

Why:
  "encapsulated" bundles the Ada runtime (RTS), which can cause
  duplicate-runtime link failures when multiple encapsulated
  libraries are combined.

  Ada toolchain ecosystems require:
    - Library_Standalone = "standard"
    - Library_Interface for public API enforcement

See:
  project SDS § Library_Standalone design decision
```

The `{gpr}` placeholder takes the GPR basename. Tests assert the entire formatted string verbatim.

### Root-GPR detection (`find_root_gpr`)

```python
def find_root_gpr(project_root: Path) -> Optional[Path]:
    primary = project_root / f"{project_root.name}.gpr"
    if primary.exists():
        return primary

    skip_suffixes = (
        '_config.gpr',
        '_internal.gpr',
        '_shared_config.gpr',
        '_spark.gpr',
        '_tests.gpr',
        '_test.gpr',
    )
    candidates = sorted(
        p for p in project_root.glob('*.gpr')
        if not p.name.endswith(skip_suffixes)
    )
    return candidates[0] if candidates else None
```

### Root-GPR validation (`_validate_root_gpr`)

```python
has_any_standalone = re.search(
    r'^\s*for\s+Library_Standalone\s+use\b',
    content, re.MULTILINE | re.IGNORECASE,
)
if not has_any_standalone:
    # Non-library project — skipped.

has_standard      = bool(re.search(r'^\s*for\s+Library_Standalone\s+use\s+"standard"\s*;', content, re.MULTILINE | re.IGNORECASE))
has_encapsulated  = bool(re.search(r'^\s*for\s+Library_Standalone\s+use\s+"encapsulated"\s*;', content, re.MULTILINE | re.IGNORECASE))
has_interface     = bool(re.search(r'for\s+Library_Interface\s+use\s*\(', content, re.IGNORECASE))

if has_encapsulated:                # → canonical error, valid=False
if not has_standard and not has_encapsulated: # → require "standard"
if not has_interface:               # → rule coupling (standard alone insufficient)
```

### Test suite layout

```
tests/
  __init__.py
  conftest.py            # sys.path bootstrap — no pytest.ini/pyproject.toml changes
  test_arch_guard_root_gpr.py
  fixtures/
    valid_root_standard.gpr
    invalid_root_encapsulated.gpr
    invalid_root_standard_no_interface.gpr
```

11 test cases cover `find_root_gpr` (4), `_validate_root_gpr` (5), `validate_config` integration (2).

## Verification chain (all green)

```bash
$ python3 -m pytest tests/ -v
tests/test_arch_guard_root_gpr.py::test_find_root_gpr_name_based PASSED
tests/test_arch_guard_root_gpr.py::test_find_root_gpr_fallback_to_only_gpr PASSED
tests/test_arch_guard_root_gpr.py::test_find_root_gpr_fallback_skips_internal_siblings PASSED
tests/test_arch_guard_root_gpr.py::test_find_root_gpr_none_when_no_gpr PASSED
tests/test_arch_guard_root_gpr.py::test_root_gpr_valid_standard_with_interface PASSED
tests/test_arch_guard_root_gpr.py::test_root_gpr_encapsulated_rejected_with_canonical_message PASSED
tests/test_arch_guard_root_gpr.py::test_root_gpr_standard_without_interface_rejected PASSED
tests/test_arch_guard_root_gpr.py::test_root_gpr_no_library_standalone_is_skipped PASSED
tests/test_arch_guard_root_gpr.py::test_root_gpr_absent_is_skipped PASSED
tests/test_arch_guard_root_gpr.py::test_validate_config_root_only_no_application PASSED
tests/test_arch_guard_root_gpr.py::test_validate_config_encapsulated_root_overrides_pass PASSED
============================== 11 passed in 0.03s ==============================

$ grep -rn 'Library_Standalone.*encapsulated' . --include='*.py' --include='*.gpr' --include='*.md'
# Only intended matches:
#   - ROOT_GPR_ENCAPSULATED_ERROR constant + reject regex in ada.py
#   - tests/fixtures/invalid_root_encapsulated.gpr (deliberate negative)
#   - tests docstring
#   - CHANGELOG migration note
#   - backup/sessions/ forensic trail
# No stale code paths.
```

## PR-level review asks for GPT

1. **`find_root_gpr` skip-suffix list completeness** — covers `_config`, `_internal`, `_shared_config`, `_spark`, `_tests`, `_test`. Right set for the abitofhelp ecosystem, or any other sibling patterns to add (e.g., `_client`, `_api_internal`, `_examples`)?

2. **Rule-coupling error message clarity** — when `standard` is present but `Library_Interface` is missing, the validator says:
   ```
   ❌ Root GPR <name>.gpr: missing required Library_Interface declaration
        Required: for Library_Interface use (...);
        WHY: defines the public API surface; stand-alone mode alone is not sufficient
   ```
   Clear enough, or should it also mention the consequence (private packages become visible)?

3. **Canonical error string as API contract** — `ROOT_GPR_ENCAPSULATED_ERROR` is exported as a module constant; tests assert the formatted string verbatim (`expected in joined`). Right level of discipline, or should tests relax to substring matching (e.g., `"encapsulated" in joined`) to tolerate future wording refinements?

4. **Verdict composition and ordering** — `validate_config()` calls `_validate_root_gpr` first, then the existing Application-GPR checks, and returns `(root_ok AND app_valid, messages)`. Messages are appended in order (root diagnostics first, app diagnostics second). Right order, or should the app-layer check fire first so developers see the most-common failure up top?

5. **Regex specificity — commented-out case** — the encapsulated reject regex `^\s*for\s+Library_Standalone\s+use\s+"encapsulated"\s*;` does NOT match a commented line like `--  for Library_Standalone use "encapsulated";`. That means:
   - ✓ commented-out code doesn't fail validation (commented ≠ live)
   - ✗ if someone toggles the comment without changing the value, the bug re-enters
   Is the current behavior the intended policy (commented code is fine until uncommented), or should we fail on any occurrence regardless of comment state?

6. **Test placement sanity** — tests co-located per locked option (a). No `pytest.ini`, no `pyproject.toml`. `conftest.py` handles the `sys.path` bootstrap so `python3 -m pytest tests/` works bare. Right minimal-config approach, or does GPT want explicit `pytest.ini` for future CI wiring?

7. **Migration note specificity** — CHANGELOG says consumers need `alr update` + rebuild after bumping the submodule. For submodule-tracked consumers (hybrid_lib_ada) the first step is `git submodule update --remote`; for Alire path-dep consumers (astfmt → astengine) it's `alr update`. Worth distinguishing in the migration text, or is a single note sufficient?

8. **Anything missed** — any edge case the test suite should cover before merge?

## Scope discipline (NOT done)

- **No** consumer-repo change (PR 2a/2b/3 ride separately)
- **No** change to Application-GPR validator behavior
- **No** layer-dependency-rule change
- **No** `Library_Interface` semantic change
- **No** `feat-compile-guides` branch interaction
- **No** changes to non-Ada adapters (C++, Go)

## Merge disposition leaning

**Approve after GPT code review sign-off.** The fix is narrow, covered by tests, and consistent with 4 rounds of planning review. If GPT flags regex edges or test rigor, auto-apply and re-push. If GPT green-lights, merge — unblocks PR 2a + PR 2b.

## References

- PR 1 pre-phase ask: `backup/sessions/20260424T100000Z__library_standalone_standard_prephase_ask.md`
- PR 1 GPT direction lock: `backup/sessions/20260424T101000Z__library_standalone_standard_gpt_direction_lock.md`
- astengine issue #10 (ESAL composition limitation)
- 4-round Claude ↔ GPT review archived in session jsonl
