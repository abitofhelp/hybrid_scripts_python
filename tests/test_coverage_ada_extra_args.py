# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
"""Tests for ``gprbuild_extra_args`` in ``makefile.coverage_ada``.

The helper exposes per-consumer scenario flags (e.g. astfmt's
``-XGNATCOLL_ICONV_OPT=`` for glibc-Linux iconv-disable) without
embedding project-specific knowledge in the shared script. Consumers
set ``GPRBUILD_EXTRA_ARGS`` in their Makefile target; the script
appends the shell-tokenised value to its ``gprbuild`` invocations.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "makefile"))

import coverage_ada  # type: ignore  # noqa: E402


def test_returns_empty_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GPRBUILD_EXTRA_ARGS", raising=False)
    assert coverage_ada.gprbuild_extra_args() == []


def test_returns_empty_when_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whitespace-only / empty values must not produce a single empty
    token. ``shlex.split('')`` already returns ``[]``; this regression
    test pins that property."""
    monkeypatch.setenv("GPRBUILD_EXTRA_ARGS", "")
    assert coverage_ada.gprbuild_extra_args() == []
    monkeypatch.setenv("GPRBUILD_EXTRA_ARGS", "   ")
    assert coverage_ada.gprbuild_extra_args() == []


def test_single_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GPRBUILD_EXTRA_ARGS", "-XGNATCOLL_ICONV_OPT=")
    assert coverage_ada.gprbuild_extra_args() == ["-XGNATCOLL_ICONV_OPT="]


def test_multiple_flags_split(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "GPRBUILD_EXTRA_ARGS", "-XFOO=bar -XBAZ=qux -XLIBRARY_TYPE=static",
    )
    assert coverage_ada.gprbuild_extra_args() == [
        "-XFOO=bar", "-XBAZ=qux", "-XLIBRARY_TYPE=static",
    ]


def test_quoted_value_with_spaces(monkeypatch: pytest.MonkeyPatch) -> None:
    """A quoted value with embedded spaces stays a single token."""
    monkeypatch.setenv(
        "GPRBUILD_EXTRA_ARGS", '-XSPACED="a b c" -XSIMPLE=42',
    )
    assert coverage_ada.gprbuild_extra_args() == [
        "-XSPACED=a b c", "-XSIMPLE=42",
    ]
