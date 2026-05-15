# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
"""Tests for ``makefile.compile_formal_docs``.

Covers the docs-asset-aware temp build (adafmt#56): a formal ``.typ``
that embeds a sibling-directory asset via ``image("../diagrams/foo.svg")``
must compile cleanly.  The pre-#56 script copied ``.typ`` sources flat
into the temp build directory, so any ``../<dir>/`` asset reference
pointed outside the Typst project root and failed with
``cannot read file outside of project root``.

The fix mirrors the project's ``docs/`` subtree into the temp build and
compiles with ``--root`` at that mirror, so cross-directory asset
references resolve.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "makefile"))

import compile_formal_docs  # type: ignore  # noqa: E402


MINIMAL_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12">'
    '<rect width="12" height="12" fill="black"/></svg>\n'
)

typst_required = pytest.mark.skipif(
    shutil.which("typst") is None,
    reason="typst compiler not on PATH",
)


def _make_project(root: Path, *, with_diagram: bool) -> None:
    """Create a minimal project tree (docs/formal/ + optional docs/diagrams/)."""
    formal = root / "docs" / "formal"
    formal.mkdir(parents=True)
    if with_diagram:
        diagrams = root / "docs" / "diagrams"
        diagrams.mkdir(parents=True)
        (diagrams / "dot.svg").write_text(MINIMAL_SVG, encoding="utf-8")
        (formal / "mini.typ").write_text(
            '= Mini\n\n#image("../diagrams/dot.svg", width: 20%)\n',
            encoding="utf-8",
        )
    else:
        (formal / "mini.typ").write_text(
            "= Mini\n\nPlain body, no cross-directory assets.\n",
            encoding="utf-8",
        )


# ----------------------------------------------------------------------
# find_project_root
# ----------------------------------------------------------------------

def test_find_project_root_from_formal_dir(tmp_path):
    _make_project(tmp_path, with_diagram=False)
    found = compile_formal_docs.find_project_root(tmp_path / "docs" / "formal")
    assert found == tmp_path.resolve()


def test_find_project_root_returns_none_when_absent(tmp_path):
    assert compile_formal_docs.find_project_root(tmp_path) is None


# ----------------------------------------------------------------------
# compile_formal_docs — render behavior
# ----------------------------------------------------------------------

def test_dry_run_does_not_compile(tmp_path):
    _make_project(tmp_path, with_diagram=True)
    templates = tmp_path / "templates"
    templates.mkdir()
    rc = compile_formal_docs.compile_formal_docs(tmp_path, templates, dry_run=True)
    assert rc == 0
    assert not (tmp_path / "docs" / "formal" / "mini.pdf").exists()


@typst_required
def test_plain_formal_doc_compiles(tmp_path):
    """A formal doc with no cross-directory assets still compiles
    (regression guard — this path worked before the #56 fix too)."""
    _make_project(tmp_path, with_diagram=False)
    templates = tmp_path / "templates"
    templates.mkdir()
    rc = compile_formal_docs.compile_formal_docs(tmp_path, templates)
    assert rc == 0
    assert (tmp_path / "docs" / "formal" / "mini.pdf").is_file()


@typst_required
def test_embedded_diagram_resolves(tmp_path):
    """Regression for adafmt#56: a formal doc embedding a sibling-dir
    asset via image("../diagrams/foo.svg") must compile.  Before the
    docs-mirror fix this failed with 'cannot read file outside of
    project root'."""
    _make_project(tmp_path, with_diagram=True)
    templates = tmp_path / "templates"
    templates.mkdir()
    rc = compile_formal_docs.compile_formal_docs(tmp_path, templates)
    assert rc == 0
    assert (tmp_path / "docs" / "formal" / "mini.pdf").is_file()


@typst_required
def test_pre_existing_pdf_in_docs_does_not_break_mirror(tmp_path):
    """A stale generated PDF anywhere under docs/ must not break the
    temp-mirror copy — generated PDFs are build outputs, not inputs."""
    _make_project(tmp_path, with_diagram=True)
    (tmp_path / "docs" / "formal" / "stale.pdf").write_bytes(b"%PDF-1.4\n")
    templates = tmp_path / "templates"
    templates.mkdir()
    rc = compile_formal_docs.compile_formal_docs(tmp_path, templates)
    assert rc == 0
    assert (tmp_path / "docs" / "formal" / "mini.pdf").is_file()


# ----------------------------------------------------------------------
# Compile-command mechanics — no typst required (monkeypatched subprocess)
# ----------------------------------------------------------------------

def test_compile_command_roots_at_docs_mirror(tmp_path, monkeypatch):
    """typst-free coverage of the fix: monkeypatch subprocess.run and
    assert the compile command is `typst compile --root <mirror>/docs`,
    that the .typ source is mirrored under <root>/formal/, and that the
    sibling diagram asset is mirrored under <root>/diagrams/ at the time
    the compiler is invoked.  Preserves coverage of the docs-mirror
    mechanics on runners without typst installed."""
    _make_project(tmp_path, with_diagram=True)
    templates = tmp_path / "templates"
    templates.mkdir()

    captured: dict = {}

    def fake_run(cmd, capture_output=False, text=False):
        captured["cmd"] = list(cmd)
        root_idx = cmd.index("--root")
        root = Path(cmd[root_idx + 1])
        captured["root"] = root
        # State checked while the temp build dir still exists:
        captured["diagram_mirrored"] = (root / "diagrams" / "dot.svg").is_file()
        captured["typ_parent"] = Path(cmd[-2]).parent.name

        class _CP:
            returncode = 0
            stdout = ""
            stderr = ""

        return _CP()

    monkeypatch.setattr(compile_formal_docs.subprocess, "run", fake_run)
    rc = compile_formal_docs.compile_formal_docs(tmp_path, templates)

    assert rc == 0
    assert captured["cmd"][:3] == ["typst", "compile", "--root"]
    assert captured["root"].name == "docs"
    assert captured["diagram_mirrored"] is True
    assert captured["typ_parent"] == "formal"
