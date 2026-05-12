# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
"""Tests for the gnatcov version-detection helpers in
``makefile.coverage_ada`` (PR for issue #5 — gnatcov 26 compatibility).

Coverage:
- ``gnatcov_major_version`` parses typical version-string shapes:
  * ``GNATcoverage 26.2.1 (sha)`` → 26
  * ``XCOV FSF 26.2`` (older format from --version) → 26
  * ``GNATcoverage 22.0.1`` → 22
  * stderr-only output (some toolchains emit version on stderr) → parsed
  * unparseable output → ``None`` (caller falls back to legacy path)
  * ``alr exec`` non-zero exit → ``None``
- ``_gnatcov_rts_implicit_with`` picks ``gnatcov_rts_full.gpr`` when the
  v22 layout is present and ``gnatcov_rts.gpr`` otherwise (v26).
- ``_gnatcov_rts_gpr_installed`` returns True iff
  ``<prefix>/share/gpr/gnatcov_rts.gpr`` is present (validates both v22
  and v26 install layouts against the same property).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "makefile"))

import coverage_ada  # type: ignore  # noqa: E402


def _make_completed_proc(returncode: int, stdout: str = "", stderr: str = ""):
    """Build a fake ``subprocess.CompletedProcess`` for monkeypatching."""
    return types.SimpleNamespace(
        returncode=returncode, stdout=stdout, stderr=stderr,
    )


@pytest.mark.parametrize(
    "stdout,stderr,expected",
    [
        ("GNATcoverage 26.2.1 (b465e28d)\n", "", 26),
        ("", "GNATcoverage 26.2.1 (b465e28d)\n", 26),
        ("XCOV FSF 26.2\n", "", 26),
        ("GNATcoverage 22.0.1\n", "", 22),
        ("GNATcoverage 1.0\n", "", 1),
        ("no version anywhere here\n", "", None),
        ("", "", None),
        # Regression: on hosts where `alr exec` emits informational
        # banners before the gnatcov line (adafmt run 25720362926,
        # 2026-05-12), the previous regex-on-combined-output
        # implementation picked up the alr/toolchain version and
        # mis-dispatched to the v22 legacy runtime-build path. The
        # marker-based parser must skip those lines and return the
        # version from the gnatcov line.
        ("alr 2.1.0\nGNATcoverage 26.2.1 (b465e28d)\n", "", 26),
        (
            "alr 2.1.0\nDetected toolchain: GNAT 15.2.1\n"
            "GPRBuild 25.0.1\nGNATcoverage 26.2.1\n",
            "",
            26,
        ),
        # No gnatcov marker anywhere — even though noise contains
        # version-shaped strings, we cannot identify gnatcov's own
        # version and must return None so the caller falls back.
        ("alr 2.1.0\nDetected toolchain: GNAT 15.2.1\n", "", None),
    ],
)
def test_gnatcov_major_version_parses_typical_outputs(
    stdout: str, stderr: str, expected: int | None, tmp_path: Path
) -> None:
    with patch.object(coverage_ada.subprocess, "run") as mock_run:
        mock_run.return_value = _make_completed_proc(0, stdout, stderr)
        got = coverage_ada.gnatcov_major_version(tmp_path)
    assert got == expected


def test_gnatcov_major_version_returns_none_on_subprocess_error(
    tmp_path: Path,
) -> None:
    with patch.object(coverage_ada.subprocess, "run") as mock_run:
        mock_run.side_effect = FileNotFoundError("alr not on PATH")
        got = coverage_ada.gnatcov_major_version(tmp_path)
    assert got is None


def test_gnatcov_major_version_returns_none_on_timeout(
    tmp_path: Path,
) -> None:
    with patch.object(coverage_ada.subprocess, "run") as mock_run:
        mock_run.side_effect = coverage_ada.subprocess.TimeoutExpired(
            cmd=["alr"], timeout=60,
        )
        got = coverage_ada.gnatcov_major_version(tmp_path)
    assert got is None


def test_gnatcov_major_version_parses_when_subprocess_returns_nonzero(
    tmp_path: Path,
) -> None:
    """Even non-zero exits can carry a parseable version string. The helper
    uses ``check=False`` and parses whatever output it sees, so callers
    don't lose v26 dispatch on a flaky alr invocation."""
    with patch.object(coverage_ada.subprocess, "run") as mock_run:
        mock_run.return_value = _make_completed_proc(
            returncode=1, stdout="GNATcoverage 26.2.1\n", stderr="warn:...\n",
        )
        got = coverage_ada.gnatcov_major_version(tmp_path)
    assert got == 26


# ---------------------------------------------------------------------------
# Layer 2: Alire install-path fallback
#
# Reproduces the second-order failure surfaced in adafmt run 25722225471
# (2026-05-12): the marker regex in Layer 1 correctly skipped the alr
# banner, but gnatcov 26.2.1's `--version` output did not contain any
# of the recognized markers, so Layer 1 returned None and the legacy
# dispatch fired anyway. Layer 2 resolves the binary path via
# `alr exec -- which gnatcov` and parses the version from the
# Alire-managed install directory:
#   .../alire/releases/gnatcov_<major>.<minor>.<patch>_<sha>/bin/gnatcov
# ---------------------------------------------------------------------------


def test_gnatcov_major_version_falls_back_to_alire_path_on_unparseable_version_output(
    tmp_path: Path,
) -> None:
    """Layer 1 misses (no marker / no version line); Layer 2 picks up
    the major version from the Alire install path."""
    with patch.object(coverage_ada.subprocess, "run") as mock_run:
        mock_run.side_effect = [
            # Call 1: gnatcov --version — empty / unparseable output
            _make_completed_proc(0, stdout="", stderr=""),
            # Call 2: which gnatcov — versioned Alire install path
            _make_completed_proc(
                0,
                stdout="/home/runner/.local/share/alire/releases/"
                "gnatcov_26.2.1_b465e28d/bin/gnatcov\n",
                stderr="",
            ),
        ]
        got = coverage_ada.gnatcov_major_version(tmp_path)
    assert got == 26


def test_gnatcov_major_version_layer2_when_version_output_has_unrelated_banners_only(
    tmp_path: Path,
) -> None:
    """Reproduces the exact run-25722225471 shape: `gnatcov --version`
    emits only an unrelated banner (no gnatcov / xcov marker line), so
    Layer 1 returns None, and Layer 2 must consult the Alire path."""
    with patch.object(coverage_ada.subprocess, "run") as mock_run:
        mock_run.side_effect = [
            _make_completed_proc(
                0,
                stdout="alr 2.1.0\nDetected toolchain: GNAT 15.2.1\n",
                stderr="",
            ),
            _make_completed_proc(
                0,
                stdout="/home/runner/.local/share/alire/releases/"
                "gnatcov_26.2.1_b465e28d/bin/gnatcov\n",
                stderr="",
            ),
        ]
        got = coverage_ada.gnatcov_major_version(tmp_path)
    assert got == 26


def test_gnatcov_major_version_returns_none_when_neither_layer_succeeds(
    tmp_path: Path,
) -> None:
    """Both probes fail to identify a version → None, so the caller
    takes the legacy path with the existing
    'Could not determine gnatcov major version' warning. Notably,
    `which gnatcov` may return a non-Alire path (e.g. /usr/bin/gnatcov)
    that contains no version — Layer 2 must return None for that
    case, not invent a version."""
    with patch.object(coverage_ada.subprocess, "run") as mock_run:
        mock_run.side_effect = [
            _make_completed_proc(0, stdout="", stderr=""),
            _make_completed_proc(0, stdout="/usr/bin/gnatcov\n", stderr=""),
        ]
        got = coverage_ada.gnatcov_major_version(tmp_path)
    assert got is None


def test_gnatcov_major_version_prefers_layer1_when_both_could_resolve(
    tmp_path: Path,
) -> None:
    """When Layer 1 finds a version, Layer 2 is not consulted. This
    matters if the Alire cache happens to hold an older crate version
    while the active `gnatcov --version` reports a newer one — Layer 1
    is the truth source for the actually-invoked binary."""
    with patch.object(coverage_ada.subprocess, "run") as mock_run:
        mock_run.side_effect = [
            _make_completed_proc(0, "GNATcoverage 26.2.1\n", ""),
            # If Layer 2 were called erroneously, this would yield 22.
            _make_completed_proc(
                0,
                stdout="/path/to/gnatcov_22.0.1_xxx/bin/gnatcov\n",
                stderr="",
            ),
        ]
        got = coverage_ada.gnatcov_major_version(tmp_path)
    assert got == 26


def test_gnatcov_major_version_layer2_returns_none_when_which_fails(
    tmp_path: Path,
) -> None:
    """If `which gnatcov` returns non-zero (e.g. gnatcov not on PATH),
    Layer 2 returns None rather than parsing whatever stderr says."""
    with patch.object(coverage_ada.subprocess, "run") as mock_run:
        mock_run.side_effect = [
            _make_completed_proc(0, stdout="", stderr=""),
            _make_completed_proc(
                1, stdout="", stderr="which: no gnatcov in (...)\n",
            ),
        ]
        got = coverage_ada.gnatcov_major_version(tmp_path)
    assert got is None


def test_gnatcov_rts_implicit_with_prefers_full_when_present(
    tmp_path: Path,
) -> None:
    (tmp_path / "share" / "gpr").mkdir(parents=True)
    (tmp_path / "share" / "gpr" / "gnatcov_rts_full.gpr").write_text(
        "project Gnatcov_Rts_Full is end Gnatcov_Rts_Full;\n",
    )
    assert (
        coverage_ada._gnatcov_rts_implicit_with(tmp_path)
        == "gnatcov_rts_full.gpr"
    )


def test_gnatcov_rts_implicit_with_falls_back_to_plain(tmp_path: Path) -> None:
    # Empty prefix or v26 layout: only gnatcov_rts.gpr (or none).
    assert (
        coverage_ada._gnatcov_rts_implicit_with(tmp_path) == "gnatcov_rts.gpr"
    )


def test_gnatcov_rts_gpr_installed_true_when_file_present(
    tmp_path: Path,
) -> None:
    gpr = tmp_path / "share" / "gpr" / "gnatcov_rts.gpr"
    gpr.parent.mkdir(parents=True)
    gpr.write_text("project Gnatcov_Rts is end Gnatcov_Rts;\n")
    assert coverage_ada._gnatcov_rts_gpr_installed(tmp_path) is True


def test_gnatcov_rts_gpr_installed_false_when_only_obj_present(
    tmp_path: Path,
) -> None:
    """Reproduces the original v26 bug: gprinstall on a v26 binary
    deposits only ``obj/`` at the prefix (no ``share/gpr/``). The helper
    must NOT return True for that incomplete state."""
    (tmp_path / "obj").mkdir()
    assert coverage_ada._gnatcov_rts_gpr_installed(tmp_path) is False


def test_gnatcov_rts_gpr_installed_false_on_empty_prefix(
    tmp_path: Path,
) -> None:
    assert coverage_ada._gnatcov_rts_gpr_installed(tmp_path) is False
