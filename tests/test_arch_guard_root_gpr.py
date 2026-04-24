# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Michael Gardner, A Bit of Help, Inc.
"""Tests for the root-library-GPR validation rule in
``arch_guard.adapters.ada`` (PR 1 of the Library_Standalone="standard"
enforcement rollout).

Coverage:
- positive: valid root with Library_Standalone="standard" + Library_Interface
- negative 1: Library_Standalone="encapsulated" must be rejected with the
  canonical :data:`ROOT_GPR_ENCAPSULATED_ERROR` message (treated as an API
  contract — exact string match).
- negative 2: rule coupling — Library_Standalone="standard" alone is not
  sufficient; Library_Interface must also be present.
- negative 3: missing Library_Standalone declaration entirely — the helper
  must still produce a deterministic "not a library / skipped" outcome.
- detection: ``find_root_gpr`` name-based lookup + ``*.gpr`` fallback.
"""

from pathlib import Path
import shutil

import pytest

from arch_guard.adapters.ada import (
    AdaAdapter,
    ROOT_GPR_ENCAPSULATED_ERROR,
    find_root_gpr,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _stage(tmp_path: Path, fixture_name: str, gpr_name: str | None = None) -> Path:
    """Copy a GPR fixture into ``tmp_path`` under ``<tmp_path>.name.gpr``
    so ``find_root_gpr``'s name-based lookup succeeds.

    Returns the staged project root path.
    """
    if gpr_name is None:
        gpr_name = f"{tmp_path.name}.gpr"
    src = FIXTURES / fixture_name
    dst = tmp_path / gpr_name
    shutil.copyfile(src, dst)
    return tmp_path


# ---------------------------------------------------------------------------
# find_root_gpr
# ---------------------------------------------------------------------------


def test_find_root_gpr_name_based(tmp_path: Path) -> None:
    """Name-based lookup finds ``<project_root.name>.gpr``."""
    root = _stage(tmp_path, "valid_root_standard.gpr")
    found = find_root_gpr(root)
    assert found is not None
    assert found.name == f"{root.name}.gpr"


def test_find_root_gpr_fallback_to_only_gpr(tmp_path: Path) -> None:
    """Fallback picks the only ``*.gpr`` at root when name lookup fails."""
    (tmp_path / "odd_named.gpr").write_text(
        (FIXTURES / "valid_root_standard.gpr").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    found = find_root_gpr(tmp_path)
    assert found is not None
    assert found.name == "odd_named.gpr"


def test_find_root_gpr_fallback_skips_internal_siblings(tmp_path: Path) -> None:
    """Fallback skips ``*_internal.gpr`` / ``*_config.gpr`` / ``*_spark.gpr``
    / ``*_shared_config.gpr`` / ``*_test*.gpr`` and picks the real root."""
    real = FIXTURES / "valid_root_standard.gpr"
    (tmp_path / "odd_named.gpr").write_text(real.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "helper_internal.gpr").write_text("-- internal\n", encoding="utf-8")
    (tmp_path / "helper_config.gpr").write_text("-- config\n", encoding="utf-8")
    (tmp_path / "helper_spark.gpr").write_text("-- spark\n", encoding="utf-8")
    (tmp_path / "helper_shared_config.gpr").write_text("-- shared\n", encoding="utf-8")
    (tmp_path / "helper_tests.gpr").write_text("-- tests\n", encoding="utf-8")

    found = find_root_gpr(tmp_path)
    assert found is not None
    assert found.name == "odd_named.gpr"


def test_find_root_gpr_none_when_no_gpr(tmp_path: Path) -> None:
    """Returns ``None`` when no GPR exists at root."""
    assert find_root_gpr(tmp_path) is None


# ---------------------------------------------------------------------------
# Root-GPR validator (_validate_root_gpr)
# ---------------------------------------------------------------------------


def test_root_gpr_valid_standard_with_interface(tmp_path: Path) -> None:
    """Valid root (standard + Library_Interface) passes."""
    adapter = AdaAdapter()
    root = _stage(tmp_path, "valid_root_standard.gpr")
    ok, messages = adapter._validate_root_gpr(root)
    assert ok is True
    joined = "\n".join(messages)
    assert "Root GPR" in joined
    assert "configuration valid" in joined


def test_root_gpr_encapsulated_rejected_with_canonical_message(tmp_path: Path) -> None:
    """Encapsulated root must fail with the exact canonical error.

    The canonical string is treated as an API contract — it's the text
    that developers will see in CI and terminals when they trip the
    rule. Any wording change in :data:`ROOT_GPR_ENCAPSULATED_ERROR`
    must be matched here.
    """
    adapter = AdaAdapter()
    root = _stage(tmp_path, "invalid_root_encapsulated.gpr")
    ok, messages = adapter._validate_root_gpr(root)
    assert ok is False

    expected = ROOT_GPR_ENCAPSULATED_ERROR.format(gpr=f"{root.name}.gpr")
    joined = "\n".join(messages)
    assert expected in joined


def test_root_gpr_standard_without_interface_rejected(tmp_path: Path) -> None:
    """Rule coupling: Library_Standalone="standard" alone is NOT sufficient.

    Library_Interface must also be present. This closes the subtle gap
    that would otherwise let a library expose every internal package.
    """
    adapter = AdaAdapter()
    root = _stage(tmp_path, "invalid_root_standard_no_interface.gpr")
    ok, messages = adapter._validate_root_gpr(root)
    assert ok is False
    joined = "\n".join(messages)
    assert "missing required Library_Interface" in joined


def test_root_gpr_no_library_standalone_is_skipped(tmp_path: Path) -> None:
    """A root GPR with no Library_Standalone line at all is treated as
    a non-library project and skipped (not failed)."""
    (tmp_path / f"{tmp_path.name}.gpr").write_text(
        "project No_Library is\n"
        "   for Source_Dirs use (\"src\");\n"
        "end No_Library;\n",
        encoding="utf-8",
    )
    adapter = AdaAdapter()
    ok, messages = adapter._validate_root_gpr(tmp_path)
    assert ok is True
    assert any("skipped" in m for m in messages)


def test_root_gpr_absent_is_skipped(tmp_path: Path) -> None:
    """When there is no root GPR at all, the check is skipped cleanly."""
    adapter = AdaAdapter()
    ok, messages = adapter._validate_root_gpr(tmp_path)
    assert ok is True
    assert any("skipped" in m for m in messages)


# ---------------------------------------------------------------------------
# validate_config (integration with existing application-GPR path)
# ---------------------------------------------------------------------------


def test_validate_config_root_only_no_application(tmp_path: Path) -> None:
    """With only a root GPR and no application layer, the final verdict
    reflects the root-GPR result."""
    adapter = AdaAdapter()
    root = _stage(tmp_path, "valid_root_standard.gpr")
    ok, messages = adapter.validate_config(root, layers_present=set())
    assert ok is True


def test_validate_config_encapsulated_root_overrides_pass(tmp_path: Path) -> None:
    """If the root is encapsulated, validate_config must fail even when
    no application layer is present (the root check is the gate)."""
    adapter = AdaAdapter()
    root = _stage(tmp_path, "invalid_root_encapsulated.gpr")
    ok, messages = adapter.validate_config(root, layers_present=set())
    assert ok is False
    joined = "\n".join(messages)
    assert "encapsulated" in joined
