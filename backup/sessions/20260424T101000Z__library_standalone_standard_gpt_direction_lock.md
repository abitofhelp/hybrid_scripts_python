# GPT Direction Lock — Library_Standalone="standard" Enforcement (PR 1)

**Date**: 2026-04-24
**Pre-phase ask**: `backup/sessions/20260424T100000Z__library_standalone_standard_prephase_ask.md`
**GPT verdict**: **APPROVED — proceed to implementation.** No further planning review needed; next meaningful review is PR 1 code review.

## Locked answers to the 6 questions

| # | Question | Locked |
|---|---|---|
| Q1 | Fixture naming | **Keep current names** — `valid_root_standard.gpr` + `invalid_root_encapsulated.gpr`. Clear, intent-driven, scoped under `tests/fixtures/`. No `_fixture.gpr` suffix needed. |
| Q2 | pytest config | **None initially.** Start with bare `python3 -m pytest tests/`. Add `tests/conftest.py` with `sys.path.insert(0, str(Path(__file__).resolve().parents[1]))` only if imports fail. No `pytest.ini` / `pyproject.toml` change. |
| Q3 | Import path | **Lazy fix only if needed.** Preferred: `from arch_guard.adapters.ada import validate_config`. If that fails, add the conftest.py path fix. |
| Q4 | Exit codes | **Single non-zero exit for all validation failures.** arch_guard is a policy gate, not a multi-mode CLI. CI only cares about pass/fail. Avoid premature complexity. |
| Q5 | CHANGELOG entry in hybrid_scripts_python | **Yes — add entry.** Tooling change that can (intentionally) break consumers. |
| Q6 | Anything missed | **Two small improvements** (see below). |

## GPT-added improvements (auto-fold into PR 1)

### Improvement 1 — Fourth negative test fixture

Current planned negative fixtures:
- `invalid_root_encapsulated.gpr` — encapsulated instead of standard ❌
- (missing Library_Interface) covered by parametric test over `valid_root_standard.gpr`
- (missing Library_Standalone) covered by parametric test

**Add:** `invalid_root_standard_no_interface.gpr` — has `standard` but no `Library_Interface`. Ensures **rule coupling** is enforced: `standard` alone is not sufficient; `Library_Interface` must also be present.

This closes a subtle gap where a GPR could pass the Library_Standalone check while missing Library_Interface.

### Improvement 2 — Strengthened grep in verification chain

Change:
```bash
grep -rn "encapsulated" .
```

To:
```bash
grep -rn 'Library_Standalone.*encapsulated' .
```

Reason: avoids noise from comments, historical text, and documentation mentions of the word "encapsulated". Ensures no **code-level** regression remains.

## CHANGELOG entry (ready-to-use, GPT-finalized)

```markdown
### Changed
- arch_guard now enforces Library_Standalone = "standard" on root GPRs
- namespace_layers no longer upgrades libraries to "encapsulated"

### Rationale
- Prevents duplicate Ada runtime (RTS) conflicts
- Aligns build configuration with architecture rules
```

## Execution plan (finalized)

1. Remove `namespace_layers.py:321-326` auto-upgrade block
2. Extend `arch_guard/adapters/ada.py` `validate_config()`:
   - Locate root GPR via `project_root / f"{project_root.name}.gpr"` (or detect by scanning for `*.gpr` files at root)
   - Scan for `for Library_Standalone use "standard";` — must be present
   - Scan for `for Library_Standalone use "encapsulated";` — must NOT be present (triggers canonical error)
   - Scan for `for Library_Interface use (...);` — must be present
   - On any root-GPR violation, emit the canonical error message (pre-phase ask § "Canonical error message") and fail the overall `validate_config()`
3. Create `tests/` dir with:
   - `tests/__init__.py`
   - `tests/conftest.py` (only if imports fail during implementation)
   - `tests/test_arch_guard_root_gpr.py` — 4+ cases:
     - positive: valid_root_standard → passes
     - negative 1: invalid_root_encapsulated → fails with canonical error
     - negative 2: invalid_root_standard_no_interface → fails (rule coupling)
     - negative 3: root GPR missing Library_Standalone entirely → fails
   - `tests/fixtures/__init__.py`
   - `tests/fixtures/valid_root_standard.gpr` — minimal valid
   - `tests/fixtures/invalid_root_encapsulated.gpr` — encapsulated
   - `tests/fixtures/invalid_root_standard_no_interface.gpr` — standard but no Library_Interface
4. Add `CHANGELOG.md` entry (ready-to-use text above)
5. Local verification:
   - `python3 -m pytest tests/` — all tests green
   - `grep -rn 'Library_Standalone.*encapsulated' .` — must return 0 code-level matches
6. Commit + push + open PR #? with review ask

## Scope discipline (confirmed)

- **No** consumer-repo change (all rides PR 2a/2b/3)
- **No** `feat-compile-guides` branch touched
- **No** existing `src/application/application.gpr` validation change
- **No** layer-dependency rule change
- **No** Library_Interface semantic change

## References

- Pre-phase ask: `backup/sessions/20260424T100000Z__library_standalone_standard_prephase_ask.md`
- Canonical error message: see pre-phase ask § "Canonical error message"
- astengine issue #10 (ESAL composition)
- Rollout PR chain: PR 1 (this) → PR 2a (hybrid_lib_ada) ‖ PR 2b (astengine) → PR 3 (astfmt)
