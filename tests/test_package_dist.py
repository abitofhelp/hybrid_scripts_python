# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
"""Unit tests for ``package_dist.package_dist`` release-packaging helpers.

Covers (per adafmt#62 RC-1 packaging design):

- ALLOWED_SYSTEM_DEPS allowlist regex behavior on good and poisoned inputs.
- ``parse_readelf_needed`` parses NEEDED entries from ``readelf -d`` output.
- ``parse_ldd_sonames`` parses dynamic deps and detects "not a dynamic
  executable" / "statically linked".
- ``include_docs_into_stage`` copies named docs and fails on missing files.
- ``create_tarball`` + ``write_sha256`` produce a top-level-dir tarball and
  matching sha256sum-compatible file; round-trip verified with
  ``sha256sum -c`` semantics (recomputed in-test).
- ``expected_manifest_entries`` allow-set shape.
- ``verify_tarball_manifest`` accepts allowed contents and rejects extras.

Fixtures use ``tmp_path``; no subprocess invocations are made beyond the
real ``tar`` and (where available) ``sha256sum`` shell tools, which are
standard on macOS and Linux runners alike.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

# package_dist lives one level down; conftest already inserted repo root.
import package_dist.package_dist as pd
from package_dist.package_dist import (
    ALLOWED_SYSTEM_DEPS,
    _allowlist_matches,
    classify_bundle_targets,
    create_tarball,
    expected_manifest_entries,
    find_patchelf,
    include_docs_into_stage,
    parse_ldd_sonames,
    parse_readelf_needed,
    patch_rpath,
    verify_resolution,
    verify_tarball_manifest,
    write_sha256,
)


# ----------------------------------------------------------------------
# Allowlist
# ----------------------------------------------------------------------

@pytest.mark.parametrize(
    "soname",
    [
        "libc.so.6",
        "libm.so.6",
        "libdl.so.2",
        "libpthread.so.0",
        "librt.so.1",
        "libgcc_s.so.1",
        "ld-linux-x86-64.so.2",
        "ld-linux-aarch64.so.1",
        "ld-linux.so.2",
        "linux-vdso.so.1",
    ],
)
def test_allowlist_accepts_system_sonames(soname):
    assert _allowlist_matches(soname), f"{soname!r} should be allowlisted"


@pytest.mark.parametrize(
    "soname",
    [
        "libcrypto.so.3",
        "libssl.so.3",
        "libgnatcoll.so.26",
        "libstdc++.so.6",
        "libiconv.so.2",
        "libz.so.1",
        "evil.so",
        "libc.so",                       # missing version suffix
        "libc.so.6.1",                    # extra version segment
        "libfoo-libc.so.6",               # name not anchored at start
    ],
)
def test_allowlist_rejects_unexpected_sonames(soname):
    assert not _allowlist_matches(soname), f"{soname!r} must NOT be allowlisted"


def test_allowlist_count_is_locked():
    # Sanity check: if someone broadens the allowlist they must update
    # this test, which forces a deliberate review.  Current allowlist
    # entries: libc, libm, libdl, libpthread, librt, libgcc_s, ld-linux,
    # linux-vdso.
    assert len(ALLOWED_SYSTEM_DEPS) == 8


# ----------------------------------------------------------------------
# readelf parsing
# ----------------------------------------------------------------------

READELF_SAMPLE_DYNAMIC = """\
Dynamic section at offset 0x1234 contains 28 entries:
  Tag        Type                         Name/Value
 0x0000000000000001 (NEEDED)             Shared library: [libgcc_s.so.1]
 0x0000000000000001 (NEEDED)             Shared library: [libpthread.so.0]
 0x0000000000000001 (NEEDED)             Shared library: [libdl.so.2]
 0x0000000000000001 (NEEDED)             Shared library: [librt.so.1]
 0x0000000000000001 (NEEDED)             Shared library: [libm.so.6]
 0x0000000000000001 (NEEDED)             Shared library: [libc.so.6]
 0x000000000000000c (INIT)               0x4010
"""

READELF_SAMPLE_POISONED = """\
 0x0000000000000001 (NEEDED)             Shared library: [libc.so.6]
 0x0000000000000001 (NEEDED)             Shared library: [libcrypto.so.3]
"""

READELF_SAMPLE_EMPTY = """\
Dynamic section at offset 0x0 contains 0 entries:
"""


def test_parse_readelf_needed_dynamic():
    got = parse_readelf_needed(READELF_SAMPLE_DYNAMIC)
    assert got == [
        "libgcc_s.so.1", "libpthread.so.0", "libdl.so.2",
        "librt.so.1", "libm.so.6", "libc.so.6",
    ]


def test_parse_readelf_needed_poisoned():
    got = parse_readelf_needed(READELF_SAMPLE_POISONED)
    assert "libcrypto.so.3" in got


def test_parse_readelf_needed_empty():
    assert parse_readelf_needed(READELF_SAMPLE_EMPTY) == []


# ----------------------------------------------------------------------
# ldd parsing
# ----------------------------------------------------------------------

LDD_SAMPLE_DYNAMIC = """\
\tlinux-vdso.so.1 (0x00007ffe2c5fe000)
\tlibgcc_s.so.1 => /lib/x86_64-linux-gnu/libgcc_s.so.1 (0x00007f1)
\tlibc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (0x00007f2)
\t/lib64/ld-linux-x86-64.so.2 (0x00007f3)
"""

LDD_SAMPLE_DYNAMIC_AARCH64 = """\
\tlinux-vdso.so.1 (0x0000ffff9c5fe000)
\tlibc.so.6 => /lib/aarch64-linux-gnu/libc.so.6 (0x0000ffff9c500000)
\t/lib/ld-linux-aarch64.so.1 (0x0000ffff9c600000)
"""

LDD_SAMPLE_POISONED = """\
\tlinux-vdso.so.1 (0x00007ffe2c5fe000)
\tlibcrypto.so.3 => /lib/x86_64-linux-gnu/libcrypto.so.3 (0x00007f1)
\tlibc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (0x00007f2)
"""

LDD_SAMPLE_NOT_DYNAMIC = "\tnot a dynamic executable\n"

LDD_SAMPLE_STATICALLY_LINKED = "\tstatically linked\n"


def test_parse_ldd_dynamic_amd64():
    sonames, is_static = parse_ldd_sonames(LDD_SAMPLE_DYNAMIC)
    assert is_static is False
    # absolute loader path normalized to basename
    assert "ld-linux-x86-64.so.2" in sonames
    assert "linux-vdso.so.1" in sonames
    assert "libc.so.6" in sonames
    assert "libgcc_s.so.1" in sonames
    assert all(_allowlist_matches(s) for s in sonames)


def test_parse_ldd_dynamic_aarch64():
    sonames, is_static = parse_ldd_sonames(LDD_SAMPLE_DYNAMIC_AARCH64)
    assert is_static is False
    assert "ld-linux-aarch64.so.1" in sonames
    assert "linux-vdso.so.1" in sonames
    assert "libc.so.6" in sonames
    assert all(_allowlist_matches(s) for s in sonames)


def test_parse_ldd_poisoned():
    sonames, is_static = parse_ldd_sonames(LDD_SAMPLE_POISONED)
    assert is_static is False
    assert "libcrypto.so.3" in sonames
    assert not _allowlist_matches("libcrypto.so.3")


def test_parse_ldd_not_a_dynamic_executable():
    sonames, is_static = parse_ldd_sonames(LDD_SAMPLE_NOT_DYNAMIC)
    assert is_static is True
    assert sonames == []


def test_parse_ldd_statically_linked():
    sonames, is_static = parse_ldd_sonames(LDD_SAMPLE_STATICALLY_LINKED)
    assert is_static is True
    assert sonames == []


# ----------------------------------------------------------------------
# include_docs_into_stage
# ----------------------------------------------------------------------

def _mkproj(tmp_path: Path, *files: str) -> Path:
    """Create a fake project root with the named files (empty bodies)."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "alire.toml").write_text("", encoding="utf-8")
    for name in files:
        (project / name).write_text(f"# {name}\n", encoding="utf-8")
    return project


def test_include_docs_success(tmp_path):
    project = _mkproj(tmp_path, "LICENSE", "README.md", "CHANGELOG.md")
    stage = tmp_path / "stage"
    stage.mkdir()
    rc = include_docs_into_stage(stage, project, ["LICENSE", "README.md", "CHANGELOG.md"])
    assert rc == 0
    assert (stage / "LICENSE").is_file()
    assert (stage / "README.md").is_file()
    assert (stage / "CHANGELOG.md").is_file()


def test_include_docs_fails_on_missing(tmp_path):
    project = _mkproj(tmp_path, "LICENSE", "README.md")  # missing CHANGELOG.md
    stage = tmp_path / "stage"
    stage.mkdir()
    rc = include_docs_into_stage(stage, project, ["LICENSE", "README.md", "CHANGELOG.md"])
    assert rc == 10


def test_include_docs_fails_on_all_missing(tmp_path):
    project = _mkproj(tmp_path)
    stage = tmp_path / "stage"
    stage.mkdir()
    rc = include_docs_into_stage(stage, project, ["LICENSE", "README.md"])
    assert rc == 10


# ----------------------------------------------------------------------
# Tarball + sha256 + manifest
# ----------------------------------------------------------------------

def _stage_release_layout(tmp_path: Path, basename: str,
                          bin_name: str = "adafmt",
                          docs: list = None,
                          bundled_libs: list = None) -> Path:
    """Create a fake staged release layout at tmp_path/dist/<basename>/."""
    docs = docs or []
    bundled_libs = bundled_libs or []
    dist = tmp_path / "dist"
    stage = dist / basename
    (stage / "bin").mkdir(parents=True)
    (stage / "bin" / bin_name).write_bytes(b"#!/bin/sh\necho fake-binary\n")
    if bundled_libs:
        (stage / "lib").mkdir()
        for libname in bundled_libs:
            (stage / "lib" / libname).write_bytes(b"\x7fELF")
    for doc in docs:
        (stage / doc).write_text(f"# {doc}\n", encoding="utf-8")
    return dist


def test_create_tarball_produces_top_level_dir(tmp_path):
    basename = "adafmt-1.0.0-rc1-linux-amd64"
    dist = _stage_release_layout(tmp_path, basename,
                                 docs=["LICENSE", "README.md"])
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    tarball, rc = create_tarball(dist, basename, output_dir)
    assert rc == 0
    assert tarball.is_file()
    assert tarball.name == f"{basename}.tar.gz"

    # tar -tzf the produced archive and confirm exactly the expected top-level dir
    cp = subprocess.run(["tar", "-tzf", str(tarball)],
                        capture_output=True, text=True, check=True)
    entries = [line for line in cp.stdout.splitlines() if line.strip()]
    # Top-level directory must be present and be the single root.
    assert f"{basename}/" in entries
    roots = {e.split("/", 1)[0] for e in entries}
    assert roots == {basename}, f"multiple roots: {roots}"


def test_create_tarball_excludes_macos_metadata(tmp_path):
    basename = "adafmt-1.0.0-rc1-linux-amd64"
    dist = _stage_release_layout(tmp_path, basename, docs=["LICENSE"])
    # Inject AppleDouble + .DS_Store files into the staged tree.
    (dist / basename / "._LICENSE").write_bytes(b"AppleDouble-fork")
    (dist / basename / "bin" / "._adafmt").write_bytes(b"AppleDouble-fork")
    (dist / basename / ".DS_Store").write_bytes(b"DS_Store-data")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    tarball, rc = create_tarball(dist, basename, output_dir)
    assert rc == 0

    cp = subprocess.run(["tar", "-tzf", str(tarball)],
                        capture_output=True, text=True, check=True)
    listing = cp.stdout
    assert "._LICENSE" not in listing
    assert "._adafmt" not in listing
    assert ".DS_Store" not in listing


def test_write_sha256_matches_recomputed_digest(tmp_path):
    basename = "adafmt-1.0.0-rc1-linux-amd64"
    dist = _stage_release_layout(tmp_path, basename)
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    tarball, rc = create_tarball(dist, basename, output_dir)
    assert rc == 0

    sha_path, rc = write_sha256(tarball)
    assert rc == 0
    assert sha_path.exists()

    line = sha_path.read_text(encoding="utf-8").strip()
    parts = line.split()
    assert len(parts) == 2, f"sha256 line malformed: {line!r}"
    declared_hash, declared_name = parts[0], parts[1]
    assert declared_name == tarball.name

    h = hashlib.sha256()
    h.update(tarball.read_bytes())
    assert declared_hash == h.hexdigest()


# ----------------------------------------------------------------------
# expected_manifest_entries + verify_tarball_manifest
# ----------------------------------------------------------------------

def test_expected_manifest_entries_minimal():
    expected = expected_manifest_entries(
        basename="adafmt-1.0.0-rc1-linux-amd64",
        bin_name="adafmt",
        doc_list=[],
        bundled_lib_names=[],
    )
    assert expected == {
        "adafmt-1.0.0-rc1-linux-amd64/",
        "adafmt-1.0.0-rc1-linux-amd64/bin/",
        "adafmt-1.0.0-rc1-linux-amd64/bin/adafmt",
    }


def test_expected_manifest_entries_with_docs_and_libs():
    expected = expected_manifest_entries(
        basename="x-amd64",
        bin_name="adafmt",
        doc_list=["LICENSE", "README.md"],
        bundled_lib_names=["libgnat-15.so", "libgnarl-15.so"],
    )
    assert "x-amd64/" in expected
    assert "x-amd64/bin/adafmt" in expected
    assert "x-amd64/lib/" in expected
    assert "x-amd64/lib/libgnat-15.so" in expected
    assert "x-amd64/lib/libgnarl-15.so" in expected
    assert "x-amd64/LICENSE" in expected
    assert "x-amd64/README.md" in expected


def test_verify_tarball_manifest_accepts_allowed(tmp_path):
    basename = "x-amd64"
    dist = _stage_release_layout(tmp_path, basename,
                                 docs=["LICENSE"])
    out = tmp_path / "out"
    out.mkdir()
    tarball, _ = create_tarball(dist, basename, out)

    expected = expected_manifest_entries(
        basename=basename, bin_name="adafmt",
        doc_list=["LICENSE"], bundled_lib_names=[],
    )
    listing, rc = verify_tarball_manifest(tarball, expected)
    assert rc == 0
    assert any(e.endswith("/bin/adafmt") for e in listing)


def test_verify_tarball_manifest_rejects_unexpected_entry(tmp_path):
    basename = "x-amd64"
    dist = _stage_release_layout(tmp_path, basename,
                                 docs=["LICENSE"])
    # Inject an unexpected file into the staged tree before tarring.
    (dist / basename / "OOPS_UNEXPECTED.txt").write_text("nope", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    tarball, _ = create_tarball(dist, basename, out)

    expected = expected_manifest_entries(
        basename=basename, bin_name="adafmt",
        doc_list=["LICENSE"], bundled_lib_names=[],
    )
    _listing, rc = verify_tarball_manifest(tarball, expected)
    assert rc == 12


# ----------------------------------------------------------------------
# classify_bundle_targets — Linux RPATH bundling decision (adafmt#62 PR-A.2)
# ----------------------------------------------------------------------

def test_classify_strict_separates_missing_and_host_nonallowlisted():
    # libgnarl-15.so is "=> not found"; libgmp.so.10 resolves from a host
    # path and is NOT allowlisted; libc.so.6 resolves and IS allowlisted.
    found = [
        ("libc.so.6", Path("/lib/x86_64-linux-gnu/libc.so.6")),
        ("libgmp.so.10", Path("/lib/x86_64-linux-gnu/libgmp.so.10")),
    ]
    missing = ["libgnarl-15.so"]
    toolchain_targets, host_targets = classify_bundle_targets(found, missing, strict=True)
    assert toolchain_targets == ["libgnarl-15.so"]
    assert host_targets == [("libgmp.so.10", Path("/lib/x86_64-linux-gnu/libgmp.so.10"))]


def test_classify_nonstrict_ignores_host_deps():
    # Without --strict-system-deps, host-resolved deps are left alone
    # (legacy behavior); only "=> not found" deps are bundled.
    found = [("libgmp.so.10", Path("/lib/x86_64-linux-gnu/libgmp.so.10"))]
    missing = ["libgnarl-15.so"]
    toolchain_targets, host_targets = classify_bundle_targets(found, missing, strict=False)
    assert toolchain_targets == ["libgnarl-15.so"]
    assert host_targets == []


def test_classify_allowlisted_host_deps_never_bundled():
    # Even in strict mode, allowlisted system libs are never bundled.
    found = [
        ("libc.so.6", Path("/lib/x86_64-linux-gnu/libc.so.6")),
        ("libm.so.6", Path("/lib/x86_64-linux-gnu/libm.so.6")),
        ("libgcc_s.so.1", Path("/lib/x86_64-linux-gnu/libgcc_s.so.1")),
    ]
    toolchain_targets, host_targets = classify_bundle_targets(found, [], strict=True)
    assert toolchain_targets == []
    assert host_targets == []


def test_classify_empty():
    assert classify_bundle_targets([], [], strict=True) == ([], [])
    assert classify_bundle_targets([], [], strict=False) == ([], [])


def test_classify_libgmp_is_bundled_in_strict_mode():
    # GPT directive: host libgmp.so.10 must be bundled (not silently left
    # as a host dependency) for the strict release path.
    found = [("libgmp.so.10", Path("/usr/lib/aarch64-linux-gnu/libgmp.so.10"))]
    _toolchain, host_targets = classify_bundle_targets(found, [], strict=True)
    assert ("libgmp.so.10", Path("/usr/lib/aarch64-linux-gnu/libgmp.so.10")) in host_targets


# ----------------------------------------------------------------------
# verify_resolution — post-RPATH-patch dependency verification
# ----------------------------------------------------------------------

def test_verify_passes_when_nonallowlisted_resolves_in_dist_lib(tmp_path):
    dist_lib = tmp_path / "dist" / "adafmt-x" / "lib"
    dist_lib.mkdir(parents=True)
    found = [
        ("libc.so.6", Path("/lib/x86_64-linux-gnu/libc.so.6")),
        ("libgnarl-15.so", dist_lib / "libgnarl-15.so"),
        ("libgmp.so.10", dist_lib / "libgmp.so.10"),
    ]
    needed = ["libc.so.6", "libgnarl-15.so", "libgmp.so.10"]
    ok, reasons = verify_resolution(needed, found, [], dist_lib, strict=True)
    assert ok is True
    assert reasons == []


def test_verify_fails_on_unresolved_dependency(tmp_path):
    dist_lib = tmp_path / "lib"
    dist_lib.mkdir()
    found = [("libc.so.6", Path("/lib/x86_64-linux-gnu/libc.so.6"))]
    missing = ["libgnarl-15.so"]
    needed = ["libc.so.6", "libgnarl-15.so"]
    ok, reasons = verify_resolution(needed, found, missing, dist_lib, strict=True)
    assert ok is False
    assert any("libgnarl-15.so" in r for r in reasons)


def test_verify_fails_strict_on_host_path_nonallowlisted(tmp_path):
    # In strict mode, a non-allowlisted dep that still resolves from a host
    # path (not from dist_lib) is a release-blocking failure.
    dist_lib = tmp_path / "lib"
    dist_lib.mkdir()
    found = [("libgmp.so.10", Path("/lib/x86_64-linux-gnu/libgmp.so.10"))]
    needed = ["libgmp.so.10"]
    ok, reasons = verify_resolution(needed, found, [], dist_lib, strict=True)
    assert ok is False
    assert any("libgmp.so.10" in r and "host path" in r for r in reasons)


def test_verify_passes_nonstrict_with_host_nonallowlisted(tmp_path):
    # Without strict, a host-resolved non-allowlisted dep is tolerated.
    dist_lib = tmp_path / "lib"
    dist_lib.mkdir()
    found = [("libgmp.so.10", Path("/lib/x86_64-linux-gnu/libgmp.so.10"))]
    needed = ["libgmp.so.10"]
    ok, reasons = verify_resolution(needed, found, [], dist_lib, strict=False)
    assert ok is True
    assert reasons == []


def test_verify_allowlisted_host_deps_are_ok(tmp_path):
    # Allowlisted system libs resolving from host paths are always fine.
    dist_lib = tmp_path / "lib"
    dist_lib.mkdir()
    found = [
        ("libc.so.6", Path("/lib/x86_64-linux-gnu/libc.so.6")),
        ("libpthread.so.0", Path("/lib/x86_64-linux-gnu/libpthread.so.0")),
    ]
    needed = ["libc.so.6", "libpthread.so.0"]
    ok, reasons = verify_resolution(needed, found, [], dist_lib, strict=True)
    assert ok is True
    assert reasons == []


def test_verify_fails_when_needed_dep_absent_from_ldd(tmp_path):
    # A NEEDED soname that appears in neither ldd found nor missing is
    # treated as unresolved (conservative).
    dist_lib = tmp_path / "lib"
    dist_lib.mkdir()
    needed = ["libphantom.so.1"]
    ok, reasons = verify_resolution(needed, [], [], dist_lib, strict=True)
    assert ok is False
    assert any("libphantom.so.1" in r for r in reasons)


# ----------------------------------------------------------------------
# find_patchelf / patch_rpath
# ----------------------------------------------------------------------

def test_find_patchelf_present(monkeypatch):
    monkeypatch.setattr(pd, "which", lambda exe: "/usr/bin/patchelf" if exe == "patchelf" else None)
    assert find_patchelf() == "/usr/bin/patchelf"


def test_find_patchelf_absent(monkeypatch):
    monkeypatch.setattr(pd, "which", lambda exe: None)
    assert find_patchelf() is None


def test_patch_rpath_builds_expected_command(monkeypatch):
    captured = {}

    def fake_run_noexcept(cmd, cwd=None):
        captured["cmd"] = cmd
        class CP:
            returncode = 0
            stdout = ""
            stderr = ""
        return CP()

    monkeypatch.setattr(pd, "run_noexcept", fake_run_noexcept)
    rc = patch_rpath(Path("/tmp/dist/adafmt-x/bin/adafmt"))
    assert rc == 0
    assert captured["cmd"][0] == "patchelf"
    assert "--set-rpath" in captured["cmd"]
    # Default RPATH must target the sibling lib/ dir (binary is under bin/).
    idx = captured["cmd"].index("--set-rpath")
    assert captured["cmd"][idx + 1] == "$ORIGIN/../lib"
    assert captured["cmd"][-1] == "/tmp/dist/adafmt-x/bin/adafmt"


def test_patch_rpath_propagates_failure(monkeypatch):
    def fake_run_noexcept(cmd, cwd=None):
        class CP:
            returncode = 1
            stdout = ""
            stderr = "patchelf: some error"
        return CP()

    monkeypatch.setattr(pd, "run_noexcept", fake_run_noexcept)
    rc = patch_rpath(Path("/tmp/dist/adafmt-x/bin/adafmt"))
    assert rc != 0
