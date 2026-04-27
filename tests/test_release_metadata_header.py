# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
"""Tests for the v2 document metadata convention in
``release.adapters.base.BaseReleaseAdapter`` (per adafmt#23).

Covers:
- ``ReleaseConfig.applies_to_range`` derivation from ``version``
- ``replace_markdown_header`` field-preservation rules:
    * Doc Version (preserve from v2 form, fall back to legacy ``**Version:**``)
    * Applies to (preserve author override, default to config range)
    * Last Updated / SPDX / License / Copyright / Status (always overwrite)
- ``add_markdown_header`` v2 emission + lenient sniff (legacy + v2 both
  detected as "header already present")
- ``_is_in_metadata_scope`` exclusions (CHANGELOG.md, LICENSE.md,
  third_party/**, generated/**, common/**)

Test fixtures use ``tmp_path`` for isolation; no real release is invoked.
"""

from pathlib import Path

import pytest

from release.adapters.ada import AdaReleaseAdapter
from release.adapters.base import BaseReleaseAdapter
from release.models import Language, ReleaseConfig


def make_config(
    project_root: Path,
    version: str = "1.0.0",
    project_name: str = "myproject",
    dry_run: bool = False,
) -> ReleaseConfig:
    """Build a minimally-populated ReleaseConfig for adapter tests."""
    cfg = ReleaseConfig(
        project_root=project_root,
        version=version,
        language=Language.ADA,
        dry_run=dry_run,
    )
    cfg.project_name = project_name
    return cfg


# ----------------------------------------------------------------------
# applies_to_range derivation
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "version,expected",
    [
        ("1.0.0", "^1.0"),
        ("4.1.7", "^4.1"),
        ("0.1.0", "^0.1"),
        ("2.0.0-rc1", "^2.0"),     # pre-release suffix stripped
        ("3.5.0+build.42", "^3.5"),  # build suffix stripped
    ],
)
def test_applies_to_range_computed_from_version(tmp_path, version, expected):
    cfg = ReleaseConfig(
        project_root=tmp_path,
        version=version,
        language=Language.ADA,
    )
    assert cfg.applies_to_range == expected


def test_applies_to_range_defensive_fallback_for_malformed_version(tmp_path):
    """A malformed single-component version still yields a parseable range."""
    cfg = ReleaseConfig(
        project_root=tmp_path,
        version="bogus",
        language=Language.ADA,
    )
    assert cfg.applies_to_range == "^0.0"


# ----------------------------------------------------------------------
# replace_markdown_header — preservation + migration
# ----------------------------------------------------------------------


@pytest.fixture
def adapter() -> BaseReleaseAdapter:
    """Concrete adapter for exercising base-class methods."""
    return AdaReleaseAdapter()


def _read_block(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_replace_legacy_form_migrates_to_v2(tmp_path, adapter):
    """A legacy header (Version/Date) is rewritten in v2 form. Doc Version
    is reset to config.version once (no v2 source to preserve from)."""
    md = tmp_path / "doc.md"
    md.write_text(
        "# Doc Title\n"
        "\n"
        "**Version:** 0.5.0<br>\n"
        "**Date:** 2025-12-01<br>\n"
        "**SPDX-License-Identifier:** BSD-3-Clause<br>\n"
        "**License File:** See the LICENSE file in the project root<br>\n"
        "**Copyright:** © 2025 Michael Gardner, A Bit of Help, Inc.<br>\n"
        "**Status:** Released\n"
        "\n"
        "Body.\n",
        encoding="utf-8",
    )

    cfg = make_config(tmp_path, version="1.0.0", project_name="myproject")
    assert adapter.replace_markdown_header(md, cfg) is True

    body = _read_block(md)
    # Doc Version reset to library version (one-time migration).
    assert "**Doc Version:** 1.0.0<br>" in body
    # Applies to set from config (no author override on legacy file).
    assert "**Applies to myproject:** ^1.0<br>" in body
    # Date renamed to Last Updated, value comes from config.
    assert f"**Last Updated:** {cfg.date_str}<br>" in body
    # Legacy field labels are gone.
    assert "**Version:**" not in body
    assert "**Date:**" not in body


def test_replace_v2_form_preserves_doc_version(tmp_path, adapter):
    """A v2 header has its existing Doc Version preserved across a release
    run (doc-author ownership)."""
    md = tmp_path / "doc.md"
    md.write_text(
        "# Doc Title\n"
        "\n"
        "**Doc Version:** 3.2.1<br>\n"
        "**Applies to myproject:** ^1.0<br>\n"
        "**Last Updated:** 2026-01-15<br>\n"
        "**SPDX-License-Identifier:** BSD-3-Clause<br>\n"
        "**License File:** See the LICENSE file in the project root<br>\n"
        "**Copyright:** © 2026 Michael Gardner, A Bit of Help, Inc.<br>\n"
        "**Status:** Released\n"
        "\n"
        "Body.\n",
        encoding="utf-8",
    )

    cfg = make_config(tmp_path, version="1.5.0", project_name="myproject")
    assert adapter.replace_markdown_header(md, cfg) is True

    body = _read_block(md)
    # Doc Version preserved unchanged.
    assert "**Doc Version:** 3.2.1<br>" in body
    # Last Updated bumped to today.
    assert f"**Last Updated:** {cfg.date_str}<br>" in body
    # Applies to follows config (no narrower override on this doc).
    assert "**Applies to myproject:** ^1.5<br>" in body


def test_replace_v2_form_preserves_applies_to_override(tmp_path, adapter):
    """An explicit narrow Applies to value is preserved (e.g., a migration
    guide that only documents 1.4.x behavior)."""
    md = tmp_path / "migration.md"
    md.write_text(
        "# Migration Guide\n"
        "\n"
        "**Doc Version:** 1.0.0<br>\n"
        "**Applies to myproject:** ~1.4.0<br>\n"
        "**Last Updated:** 2026-02-01<br>\n"
        "**SPDX-License-Identifier:** BSD-3-Clause<br>\n"
        "**License File:** See the LICENSE file in the project root<br>\n"
        "**Copyright:** © 2026 Michael Gardner, A Bit of Help, Inc.<br>\n"
        "**Status:** Released\n",
        encoding="utf-8",
    )

    cfg = make_config(tmp_path, version="2.0.0", project_name="myproject")
    assert adapter.replace_markdown_header(md, cfg) is True

    body = _read_block(md)
    # Author override preserved verbatim.
    assert "**Applies to myproject:** ~1.4.0<br>" in body
    # Doc Version preserved.
    assert "**Doc Version:** 1.0.0<br>" in body


def test_replace_idempotent_on_unchanged_input(tmp_path, adapter):
    """Running replace twice with the same config yields no second change."""
    md = tmp_path / "doc.md"
    md.write_text(
        "# Doc\n"
        "\n"
        "**Doc Version:** 1.0.0<br>\n"
        "**Applies to myproject:** ^1.0<br>\n"
        "**Last Updated:** 2099-01-01<br>\n"
        "**SPDX-License-Identifier:** BSD-3-Clause<br>\n"
        "**License File:** See the LICENSE file in the project root<br>\n"
        "**Copyright:** © 2099 Michael Gardner, A Bit of Help, Inc.<br>\n"
        "**Status:** Released\n",
        encoding="utf-8",
    )
    cfg = make_config(tmp_path, version="1.0.0", project_name="myproject")
    # First run will overwrite Last Updated and Copyright year.
    adapter.replace_markdown_header(md, cfg)
    snapshot = _read_block(md)
    # Second run must produce zero further changes (returns False).
    second = adapter.replace_markdown_header(md, cfg)
    assert second is False
    assert _read_block(md) == snapshot


# ----------------------------------------------------------------------
# add_markdown_header — new convention emission + lenient sniff
# ----------------------------------------------------------------------


def test_add_header_scaffolds_v2_convention(tmp_path, adapter):
    """A doc with a title but no header gets the v2 convention scaffolded."""
    md = tmp_path / "doc.md"
    md.write_text("# Doc Title\n\nBody.\n", encoding="utf-8")

    cfg = make_config(tmp_path, version="1.0.0", project_name="myproject")
    assert adapter.add_markdown_header(md, cfg) is True

    body = _read_block(md)
    assert "**Doc Version:** 1.0.0<br>" in body
    assert "**Applies to myproject:** ^1.0<br>" in body
    assert f"**Last Updated:** {cfg.date_str}<br>" in body
    assert "**Status:** Released" in body


def test_add_header_skips_if_legacy_present(tmp_path, adapter):
    """A legacy header is detected by the sniff; no second header added."""
    md = tmp_path / "doc.md"
    original = (
        "# Doc Title\n"
        "\n"
        "**Version:** 0.5.0<br>\n"
        "**Date:** 2025-12-01<br>\n"
        "**Status:** Released\n"
    )
    md.write_text(original, encoding="utf-8")

    cfg = make_config(tmp_path, version="1.0.0")
    assert adapter.add_markdown_header(md, cfg) is False
    assert _read_block(md) == original


def test_add_header_skips_if_v2_present(tmp_path, adapter):
    """A v2 header is detected by the sniff; no second header added."""
    md = tmp_path / "doc.md"
    original = (
        "# Doc Title\n"
        "\n"
        "**Doc Version:** 1.0.0<br>\n"
        "**Applies to myproject:** ^1.0<br>\n"
        "**Last Updated:** 2026-04-26<br>\n"
        "**Status:** Released\n"
    )
    md.write_text(original, encoding="utf-8")

    cfg = make_config(tmp_path, version="1.0.0")
    assert adapter.add_markdown_header(md, cfg) is False
    assert _read_block(md) == original


# ----------------------------------------------------------------------
# Scope narrowing
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "rel_path,expected",
    [
        ("docs/quick_start.md", True),
        ("README.md", True),
        ("CHANGELOG.md", False),       # release-per-version content
        ("LICENSE.md", False),         # boilerplate
        ("LICENSE", False),
        ("third_party/foo/README.md", False),
        ("generated/api.md", False),
        ("docs/common/shared.md", False),  # submodule shared content
        ("docs/guides/user_guide.md", True),
    ],
)
def test_is_in_metadata_scope(tmp_path, rel_path, expected):
    """Verify scope narrowing matches GPT-recommended exclusions."""
    full = tmp_path / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text("placeholder", encoding="utf-8")

    assert (
        BaseReleaseAdapter._is_in_metadata_scope(full, tmp_path) is expected
    ), f"{rel_path} expected scope={expected}"


def test_update_all_excludes_changelog(tmp_path, adapter):
    """End-to-end: ``update_all_markdown_files`` skips CHANGELOG.md even
    when CHANGELOG carries a header-shaped block."""
    (tmp_path / "docs").mkdir()
    target = tmp_path / "docs" / "quick_start.md"
    target.write_text(
        "# Quick Start\n\n"
        "**Doc Version:** 1.0.0<br>\n"
        "**Applies to myproject:** ^1.0<br>\n"
        "**Last Updated:** 2026-01-01<br>\n"
        "**SPDX-License-Identifier:** BSD-3-Clause<br>\n"
        "**License File:** See the LICENSE file in the project root<br>\n"
        "**Copyright:** © 2026 Michael Gardner, A Bit of Help, Inc.<br>\n"
        "**Status:** Released\n",
        encoding="utf-8",
    )
    changelog = tmp_path / "CHANGELOG.md"
    changelog_original = (
        "# Changelog\n\n"
        "**Version:** Unreleased<br>\n"
        "**Date:** 2025-12-01<br>\n"
        "## [Unreleased]\n"
    )
    changelog.write_text(changelog_original, encoding="utf-8")

    cfg = make_config(tmp_path, version="2.0.0", project_name="myproject")
    count = adapter.update_all_markdown_files(cfg)

    # Only the in-scope file was updated.
    assert count == 1
    # CHANGELOG untouched.
    assert _read_block(changelog) == changelog_original
    # Quick start migrated to new applies_to.
    assert "**Applies to myproject:** ^2.0<br>" in _read_block(target)


# ----------------------------------------------------------------------
# Lenient detection (find_markdown_files)
# ----------------------------------------------------------------------


def test_find_markdown_files_detects_legacy_and_v2(tmp_path, adapter):
    """Both legacy and v2 cover-page headers are found by detection."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "legacy.md").write_text(
        "# X\n**Version:** 0.1.0<br>\n", encoding="utf-8"
    )
    (tmp_path / "docs" / "v2.md").write_text(
        "# X\n**Doc Version:** 0.1.0<br>\n", encoding="utf-8"
    )
    # Non-doc file with no metadata-shape content — must NOT be matched.
    (tmp_path / "docs" / "notes.md").write_text(
        "# Notes\n\nFreeform content with no header markers.\n",
        encoding="utf-8",
    )

    found = {p.name for p in adapter.find_markdown_files(tmp_path)}
    assert found == {"legacy.md", "v2.md"}


def test_find_markdown_files_excludes_changelog_even_with_header(tmp_path, adapter):
    """CHANGELOG.md is scope-excluded even if it contains header-shaped lines."""
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n**Version:** 1.0.0<br>\n", encoding="utf-8"
    )
    found = adapter.find_markdown_files(tmp_path)
    assert found == []
