#!/usr/bin/env python3
"""
package_dist.py — Build + create relocatable dist/ bundle for an Alire GNAT Ada CLI.

Core features:
- Auto-detect binary name from ./bin if exactly one executable (else require --bin-name).
- Auto-run a /tmp smoke test and print PASS/FAIL.
- Linux: bundle only missing shared libs ("=> not found") by searching Alire toolchains.
- macOS: bundle dylibs, rewrite to @rpath, ensure @executable_path/../lib rpath.
- macOS: optional ad-hoc codesign of dist/ via --codesign.
- macOS: always run `install_name_tool -add_rpath @executable_path/../lib dist/bin/<exe>` (harmless if already present).
- Smoke test: supports "usage-style" CLIs that exit non-zero when printing usage.

Release-packaging features:
- --tarball <basename> (REQUIRED): stage under dist/<basename>/, produce
  <project>/<basename>.tar.gz containing the single top-level <basename>/
  directory, emit <project>/<basename>.tar.gz.sha256 in sha256sum-compatible
  format, run a manifest allow-set check against the tarball contents, and
  stream the final `tar -tzf` listing to stdout for workflow-log visibility.
  macOS AppleDouble/resource-fork files (._*, .DS_Store) and xattr-derived
  metadata are excluded.
- --include-docs <comma-separated paths> (optional): copy named project-root
  docs into the staged tree.  Missing files fail (no silent skipping) —
  release artifacts must not ship without their required documentation.
- --strict-system-deps (optional): Linux only.  After bundling, verify the
  binary's dynamic dependencies match a narrow system-library allowlist; fail
  on any unexpected entry.  Three success paths: (a) dynamic binary with only
  allowlisted system deps, (b) fully/static-mostly binary reporting "not a
  dynamic executable" / "statically linked", (c) parsed-as-empty NEEDED list.
  Prefers `readelf -d` for NEEDED entries; falls back to `ldd` parsing.

Layout:
  project/
    bin/<exe>
    dist/<basename>/
      bin/<exe>
      lib/(runtime libs, if any)
      LICENSE                       # if --include-docs lists it
      THIRD_PARTY_LICENSES.md
      README.md
      CHANGELOG.md
    <basename>.tar.gz
    <basename>.tar.gz.sha256

Usage:
  python3 package_dist.py --tarball adafmt-1.0.0-rc1-linux-amd64
  python3 package_dist.py --tarball adafmt-1.0.0-rc1-linux-amd64 \
    --include-docs LICENSE,THIRD_PARTY_LICENSES.md,README.md,CHANGELOG.md \
    --strict-system-deps
  python3 package_dist.py --tarball <basename> --bin-name adafmt --no-build
  python3 package_dist.py --tarball <basename> --test-args "--help" --expect-exit 0
  python3 package_dist.py --tarball <basename> --codesign  # macOS only

Exit codes:
  0  success
  1  generic failure (also: smoke test FAIL when --expect-exit not given and no marker matched)
  2  missing alire.toml in --project-dir
  3  alr build failed
  4  --bin-name auto-detect ambiguous
  5  binary not found in bin/
  6  Linux ldd bundling still reports missing deps after copy pass
  7  unsupported platform
  8  smoke test FAIL with --expect-exit / explicit pass-marker mismatch
  9  --strict-system-deps allowlist violation
  10 --include-docs missing a named file
  11 --tarball creation or sha256 step failed
  12 --tarball manifest check found an unexpected entry

Notes:
- Linux relies on: ldd, readelf (preferred for NEEDED parsing), tar, sha256sum.
- macOS relies on: otool, install_name_tool (Xcode CLI tools), tar, shasum or sha256sum.
- macOS codesign (optional): codesign.
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

ALIRE_TOOLCHAINS_DEFAULT = Path.home() / ".local" / "share" / "alire" / "toolchains"


# Linux system-library allowlist for --strict-system-deps.  Matched against
# the soname (basename) reported by readelf NEEDED / ldd, not against the
# resolved absolute path.  Keeping this narrow is intentional: anything else
# entering the closure is treated as a release-blocking surprise.
ALLOWED_SYSTEM_DEPS = [
    re.compile(r'^libc\.so\.[0-9]+$'),
    re.compile(r'^libm\.so\.[0-9]+$'),
    re.compile(r'^libdl\.so\.[0-9]+$'),
    re.compile(r'^libpthread\.so\.[0-9]+$'),
    re.compile(r'^librt\.so\.[0-9]+$'),
    re.compile(r'^libgcc_s\.so\.[0-9]+$'),
    re.compile(r'^ld-linux(-aarch64|-x86-64)?\.so\.[0-9]+$'),
    re.compile(r'^linux-vdso\.so\.[0-9]+$'),
]

# macOS metadata patterns excluded from tarballs (and stripped from the
# staged tree before tarring when running on a macOS host).
MACOS_METADATA_EXCLUDES = ('._*', '.DS_Store')


# -------------------------
# Small utilities
# -------------------------

def run(cmd: List[str], cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd))
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True, check=check)

def run_noexcept(cmd: List[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd))
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True)

def which(exe: str) -> Optional[str]:
    return shutil.which(exe)

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def is_executable_file(p: Path) -> bool:
    try:
        st = p.stat()
    except FileNotFoundError:
        return False
    if not p.is_file():
        return False
    # executable bit for someone
    return bool(st.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))

def copy2_exec(src: Path, dst: Path) -> None:
    ensure_dir(dst.parent)
    shutil.copy2(src, dst)
    # ensure executable bit
    dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

def banner(msg: str) -> None:
    print("\n" + "=" * 78)
    print(msg)
    print("=" * 78)

def fail(msg: str, code: int = 1) -> int:
    print(f"! {msg}")
    return code


# -------------------------
# Binary detection
# -------------------------

def detect_single_bin(bin_dir: Path) -> Optional[str]:
    if not bin_dir.exists() or not bin_dir.is_dir():
        return None
    candidates = []
    for p in sorted(bin_dir.iterdir()):
        if p.is_file() and is_executable_file(p):
            # exclude common non-exe artifacts if any
            if p.name.endswith((".map", ".txt", ".json", ".md")):
                continue
            candidates.append(p.name)
    if len(candidates) == 1:
        return candidates[0]
    return None


# -------------------------
# Linux helpers
# -------------------------

_LDD_FOUND = re.compile(r"^\s*(?P<name>\S+)\s+=>\s+(?P<path>\S+)\s+\(0x[0-9a-fA-F]+\)\s*$")
_LDD_NOTFOUND = re.compile(r"^\s*(?P<name>\S+)\s+=>\s+not found\s*$")

def parse_ldd(output: str) -> Tuple[List[Tuple[str, Path]], List[str]]:
    found: List[Tuple[str, Path]] = []
    missing: List[str] = []
    for line in output.splitlines():
        m_nf = _LDD_NOTFOUND.match(line)
        if m_nf:
            missing.append(m_nf.group("name"))
            continue
        m = _LDD_FOUND.match(line)
        if m:
            found.append((m.group("name"), Path(m.group("path"))))
    return found, missing

def find_files_under(root: Path, patterns: List[str]) -> List[Path]:
    """
    Return first matches found under root for each pattern, preserving overall discovery order.
    Uses 'find' if available for speed.
    """
    matches: List[Path] = []
    if not root.exists():
        return matches

    if which("find"):
        for pat in patterns:
            cp = run_noexcept(["find", str(root), "-type", "f", "-name", pat])
            for line in cp.stdout.splitlines():
                p = Path(line.strip())
                if p.exists():
                    matches.append(p)
    else:
        # Fallback (slower)
        for pat in patterns:
            matches.extend([p for p in root.rglob(pat) if p.is_file()])

    # Dedup preserving order
    seen = set()
    out = []
    for p in matches:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out

def copy_soname_family_linux(libfile: Path, dist_lib: Path) -> None:
    """
    Copy libfile plus typical siblings (libfoo.so*, libfoo-15.so*, etc.) from the same directory.
    """
    ensure_dir(dist_lib)
    parent = libfile.parent
    name = libfile.name

    # Always copy the chosen file
    shutil.copy2(libfile, dist_lib / libfile.name)

    # Copy siblings
    sibling_candidates = set()
    if ".so" in name:
        base = name.split(".so")[0] + ".so"
        for p in parent.glob(base + "*"):
            if p.is_file():
                sibling_candidates.add(p)
        for p in parent.glob(name + "*"):
            if p.is_file():
                sibling_candidates.add(p)

    for p in sorted(sibling_candidates):
        try:
            shutil.copy2(p, dist_lib / p.name)
        except Exception:
            pass

def linux_bundle_missing(binary: Path, dist_lib: Path, toolchains_root: Path) -> Tuple[bool, List[str]]:
    cp = run(["ldd", str(binary)], check=True)
    _, missing = parse_ldd(cp.stdout)
    if not missing:
        print("  - Linux: no missing deps (ldd).")
        return True, []

    banner("Linux: bundling missing libraries only")
    print("Missing:", ", ".join(missing))

    ensure_dir(dist_lib)

    for libname in missing:
        # Try exact name and common variants
        patterns = [libname]
        if libname.endswith(".so"):
            patterns.append(libname + "*")
        # Also try base.so* (handles libgnarl-15.so.15, etc.)
        if ".so" in libname:
            base = libname.split(".so")[0] + ".so*"
            patterns.append(base)

        hits = find_files_under(toolchains_root, patterns)
        if not hits:
            print(f"! Could not locate {libname} under {toolchains_root}")
            continue

        chosen = hits[0]
        print(f"  - Found {libname} at: {chosen}")
        copy_soname_family_linux(chosen, dist_lib)

    # Re-check
    cp2 = run(["ldd", str(binary)], check=True)
    _, missing2 = parse_ldd(cp2.stdout)
    ok = len(missing2) == 0
    if ok:
        print("  - Linux: all deps resolved after bundling.")
    else:
        print("! Linux: still missing:", ", ".join(missing2))
    return ok, missing2


# -------------------------
# macOS helpers
# -------------------------

_OTOOL_DEP = re.compile(r"^\s*(?P<path>\S+)\s+\(compatibility version .*", re.IGNORECASE)

def parse_otool_L(output: str) -> List[str]:
    deps: List[str] = []
    lines = output.splitlines()
    for line in lines[1:]:
        m = _OTOOL_DEP.match(line.strip())
        if m:
            deps.append(m.group("path"))
    return deps

def macos_add_rpath(binary: Path, rpath: str = "@executable_path/../lib") -> None:
    if not which("install_name_tool"):
        raise RuntimeError("install_name_tool not found (install Xcode command line tools).")
    # -add_rpath errors if duplicate; that's fine
    cp = run_noexcept(["install_name_tool", "-add_rpath", rpath, str(binary)])
    if cp.returncode == 0:
        print(f"  - macOS: added rpath {rpath}")
    else:
        print("  - macOS: rpath already present (or could not add); continuing.")

def macos_add_dist_rpath(dist_bin: Path) -> None:
    """
    Ensure dist/bin/<exe> has: @executable_path/../lib in its rpath.
    Harmless if already present.
    This is the exact command requested:
      install_name_tool -add_rpath @executable_path/../lib dist/bin/<exe>
    """
    if not which("install_name_tool"):
        raise RuntimeError("install_name_tool not found (install Xcode command line tools).")
    cp = run_noexcept(["install_name_tool", "-add_rpath", "@executable_path/../lib", str(dist_bin)])
    if cp.returncode == 0:
        print("  - macOS: added dist rpath @executable_path/../lib")
    else:
        print("  - macOS: dist rpath already present (or could not add); continuing.")

def macos_copy_needed_dylibs(binary: Path, dist_lib: Path) -> List[Path]:
    """
    Copy non-system dylibs referenced by the binary into dist/lib (direct dependencies only).
    """
    if not which("otool"):
        raise RuntimeError("otool not found (Xcode command line tools required).")

    cp = run(["otool", "-L", str(binary)], check=True)
    deps = parse_otool_L(cp.stdout)

    ensure_dir(dist_lib)
    bundled: List[Path] = []

    banner("macOS: bundling non-system dylibs")
    for dep in deps:
        if dep.startswith("@"):
            # We'll handle rewriting; can't resolve here reliably
            continue
        p = Path(dep)
        if not p.exists():
            continue
        # Skip system libs
        if str(p).startswith("/usr/lib/") or str(p).startswith("/System/Library/"):
            continue
        dst = dist_lib / p.name
        print(f"  - Copy {p} -> {dst}")
        shutil.copy2(p, dst)
        bundled.append(dst)

    return bundled

def macos_rewrite_to_rpath(binary: Path, dist_lib: Path) -> None:
    """
    Set bundled dylib IDs to @rpath/<name> and rewrite binary + dylib references to @rpath/<name>.
    """
    if not which("install_name_tool"):
        raise RuntimeError("install_name_tool not found (install Xcode command line tools).")

    dylibs = sorted(dist_lib.glob("*.dylib"))

    # Set IDs
    for d in dylibs:
        cp = run_noexcept(["install_name_tool", "-id", f"@rpath/{d.name}", str(d)])
        if cp.returncode == 0:
            print(f"  - Set dylib id: {d.name} -> @rpath/{d.name}")

    # Rewrite binary references
    cpb = run(["otool", "-L", str(binary)], check=True)
    deps = parse_otool_L(cpb.stdout)
    for dep in deps:
        if dep.startswith("@"):
            continue
        dep_path = Path(dep)
        candidate = dist_lib / dep_path.name
        if candidate.exists():
            run(["install_name_tool", "-change", dep, f"@rpath/{dep_path.name}", str(binary)], check=True)
            print(f"  - Rewrote binary dep: {dep_path.name} -> @rpath/{dep_path.name}")

    # Rewrite dylib-to-dylib references
    for d in dylibs:
        cpd = run(["otool", "-L", str(d)], check=True)
        deps2 = parse_otool_L(cpd.stdout)
        for dep in deps2:
            if dep.startswith("@"):
                continue
            dep_path = Path(dep)
            candidate = dist_lib / dep_path.name
            if candidate.exists():
                run(["install_name_tool", "-change", dep, f"@rpath/{dep_path.name}", str(d)], check=True)
                print(f"  - Rewrote {d.name} dep: {dep_path.name} -> @rpath/{dep_path.name}")


def macos_codesign_dist(dist_dir: Path) -> None:
    """
    Ad-hoc codesign dist/ (bin + dylibs). Useful for local running in some environments.
    """
    if not which("codesign"):
        print("! codesign not found; skipping.")
        return

    banner("macOS: ad-hoc codesign dist/")
    # Sign dylibs first, then the binary (deep generally OK, but explicit is clearer)
    dylibs = sorted((dist_dir / "lib").glob("*.dylib"))
    bin_dir = dist_dir / "bin"

    for d in dylibs:
        run(["codesign", "--force", "--sign", "-", str(d)], check=True)

    # Sign all executables in dist/bin (typically just one)
    for exe in sorted(bin_dir.iterdir()):
        if exe.is_file() and is_executable_file(exe):
            run(["codesign", "--force", "--sign", "-", str(exe)], check=True)


# -------------------------
# Release-packaging helpers
# -------------------------

def include_docs_into_stage(stage_root: Path, project: Path, doc_list: List[str]) -> int:
    """
    Copy each named project-root doc into the staged tree at stage_root/.
    Fails with exit 10 on any missing file — release artifacts must not
    ship without their required documentation.
    Returns 0 on success or the exit code on failure.
    """
    banner("Include required docs")
    missing: List[Path] = []
    for name in doc_list:
        src = (project / name).resolve()
        if not src.is_file():
            missing.append(src)
            print(f"! Required doc not found: {src}")
            continue
        dst = stage_root / src.name
        shutil.copy2(src, dst)
        print(f"  - Copied: {src} -> {dst}")
    if missing:
        print(f"! --include-docs: {len(missing)} required doc(s) missing; failing.")
        return 10
    return 0


def strip_macos_metadata(stage_root: Path) -> None:
    """
    On a macOS host, strip extended attributes from the staged tree and
    remove any AppleDouble (`._*`) or `.DS_Store` files that may have
    landed during copy.  No-op on non-Darwin hosts (but still walks the
    tree to remove any of those files if they exist, since they could
    have been carried in via a network/USB share).
    """
    if platform.system().lower() == "darwin" and which("xattr"):
        run_noexcept(["xattr", "-c", "-r", str(stage_root)])
        print("  - macOS: stripped xattrs from staged tree.")

    removed = 0
    for p in stage_root.rglob("._*"):
        if p.is_file():
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    for p in stage_root.rglob(".DS_Store"):
        if p.is_file():
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    if removed:
        print(f"  - Removed {removed} macOS metadata file(s) from staged tree.")


# ---- Linux strict-system-deps -------------------------------------------------

_READELF_NEEDED_RE = re.compile(
    r"\(NEEDED\)\s+Shared library:\s+\[(?P<soname>[^\]]+)\]"
)

# Matches any of:
#   "linux-vdso.so.1 (0xADDR)"        — vDSO, no `=>`
#   "libc.so.6 => /lib/.../libc.so.6 (0xADDR)" — regular dep
#   "/lib64/ld-linux-x86-64.so.2 (0xADDR)" — dynamic loader, absolute
# Captures the soname (basename) for allowlist matching.
_LDD_ANY_RE = re.compile(
    r"^\s*"
    r"(?:(?P<soname>\S+)\s+=>\s+\S+|"            # name => path
    r"(?P<vdso>\S+)\s+\(0x[0-9a-fA-F]+\)|"        # name (addr)   — vdso
    r"(?P<absloader>/\S+)\s+\(0x[0-9a-fA-F]+\))"  # /path (addr)  — loader
)

# Detect "not a dynamic executable" / "statically linked" via lowercased substring
# scan — output text differs across libc versions (musl, glibc) and locales.
_LDD_STATIC_HINTS = (
    "not a dynamic executable",
    "statically linked",
)


def parse_readelf_needed(output: str) -> List[str]:
    """Return the soname list from `readelf -d <binary>` output."""
    return _READELF_NEEDED_RE.findall(output)


def parse_ldd_sonames(output: str) -> Tuple[List[str], bool]:
    """
    Parse `ldd <binary>` output.
    Returns (list_of_sonames_basenames, is_statically_linked).
    The soname list normalizes absolute-path loader entries to their basename.
    """
    lowered = output.lower()
    if any(hint in lowered for hint in _LDD_STATIC_HINTS):
        return [], True

    sonames: List[str] = []
    for line in output.splitlines():
        m = _LDD_ANY_RE.match(line)
        if not m:
            continue
        name = m.group("soname") or m.group("vdso") or m.group("absloader") or ""
        if not name:
            continue
        # Normalize absolute loader path to basename for allowlist match.
        if name.startswith("/"):
            name = Path(name).name
        sonames.append(name)
    return sonames, False


def _allowlist_matches(soname: str) -> bool:
    return any(rx.match(soname) for rx in ALLOWED_SYSTEM_DEPS)


def enforce_strict_system_deps(binary: Path) -> int:
    """
    Linux only.  Verify the binary's dynamic dependency closure matches
    ALLOWED_SYSTEM_DEPS.  Prefers `readelf -d`; falls back to `ldd`.
    Returns 0 on success, 9 on disallowed entries.

    Three success paths:
      (a) dynamic binary, every NEEDED soname is in ALLOWED_SYSTEM_DEPS.
      (b) statically-linked binary (ldd "not a dynamic executable" /
          "statically linked").
      (c) parsed-as-empty NEEDED list (both readelf and ldd report no deps).
    """
    banner("Strict system-deps check")

    sonames: List[str] = []
    used_tool = ""

    if which("readelf"):
        cp = run_noexcept(["readelf", "-d", str(binary)])
        if cp.returncode == 0:
            sonames = parse_readelf_needed(cp.stdout)
            used_tool = "readelf"
            print(f"  - readelf NEEDED: {sonames if sonames else '(empty)'}")
        else:
            # readelf failed (not an ELF? cross-platform binary?) — fall through to ldd.
            print(f"  - readelf failed (exit {cp.returncode}); trying ldd.")

    if used_tool != "readelf":
        if not which("ldd"):
            print("! Neither readelf nor ldd is available; cannot verify deps.")
            return 9
        cp = run_noexcept(["ldd", str(binary)])
        # ldd typically exits 0 for dynamic binaries and 1 for "not a dynamic
        # executable"; both are inspected.  Stdout+stderr are combined because
        # static binaries often print the message on stderr.
        combined = (cp.stdout or "") + "\n" + (cp.stderr or "")
        sonames, is_static = parse_ldd_sonames(combined)
        used_tool = "ldd"
        if is_static:
            print("  - ldd: binary is statically linked (not a dynamic executable).")
            print("  - strict-system-deps: PASS (static binary).")
            return 0
        print(f"  - ldd sonames: {sonames if sonames else '(empty)'}")

    if not sonames:
        print(f"  - {used_tool}: empty NEEDED list.")
        print("  - strict-system-deps: PASS (no dynamic deps).")
        return 0

    disallowed = [s for s in sonames if not _allowlist_matches(s)]
    if disallowed:
        print("! strict-system-deps: disallowed deps:")
        for d in disallowed:
            print(f"    - {d}")
        print(f"  - allowlist: {[rx.pattern for rx in ALLOWED_SYSTEM_DEPS]}")
        return 9

    print("  - strict-system-deps: PASS (all deps allowlisted).")
    return 0


# ---- Tarball + sha256 + manifest -----------------------------------------------

def create_tarball(dist_dir: Path, basename: str, output_dir: Path) -> Tuple[Path, int]:
    """
    Create <output_dir>/<basename>.tar.gz containing the single top-level
    directory <basename>/ from <dist_dir>/<basename>/.
    Excludes macOS AppleDouble (._*) and .DS_Store files.
    Returns (tarball_path, exit_code).  exit_code = 0 on success, 11 on failure.
    """
    banner("Create tarball")
    tarball = output_dir / f"{basename}.tar.gz"

    cmd = [
        "tar",
        "--exclude=._*",
        "--exclude=.DS_Store",
        "-C", str(dist_dir),
        "-czf", str(tarball),
        basename,
    ]
    cp = run_noexcept(cmd)
    if cp.returncode != 0:
        if cp.stdout.strip():
            print(cp.stdout.rstrip())
        if cp.stderr.strip():
            print(cp.stderr.rstrip(), file=sys.stderr)
        print(f"! tar failed (exit {cp.returncode}); failing.")
        return tarball, 11

    if not tarball.is_file():
        print(f"! tar reported success but {tarball} is missing; failing.")
        return tarball, 11

    print(f"  - Created: {tarball}")
    return tarball, 0


def write_sha256(tarball: Path) -> Tuple[Path, int]:
    """
    Emit <tarball>.sha256 in sha256sum-compatible format
    (`<hash>  <filename>`).  Filename is the basename only so the
    file works regardless of where consumers download it.
    Returns (sha_path, exit_code).
    """
    sha_path = tarball.with_name(tarball.name + ".sha256")
    try:
        import hashlib
        h = hashlib.sha256()
        with tarball.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        digest = h.hexdigest()
        sha_path.write_text(f"{digest}  {tarball.name}\n", encoding="utf-8")
        print(f"  - Wrote: {sha_path}")
        print(f"  - sha256: {digest}")
        return sha_path, 0
    except OSError as exc:
        print(f"! sha256 emission failed: {exc}")
        return sha_path, 11


def expected_manifest_entries(basename: str, bin_name: str,
                              doc_list: List[str],
                              bundled_lib_names: List[str]) -> set:
    """
    Build the allow-set of expected tar -tzf entries.  tar lists directories
    with a trailing slash and files without.  The expected set always includes
    the top-level <basename>/ directory and <basename>/bin/<exe>; the lib/
    directory and its entries are included only if any libs were bundled; each
    --include-docs entry is included as <basename>/<doc>.
    """
    expected: set = set()
    expected.add(f"{basename}/")
    expected.add(f"{basename}/bin/")
    expected.add(f"{basename}/bin/{bin_name}")
    if bundled_lib_names:
        expected.add(f"{basename}/lib/")
        for libname in bundled_lib_names:
            expected.add(f"{basename}/lib/{libname}")
    for doc in doc_list:
        # Basename only — --include-docs flattens names to stage_root/.
        expected.add(f"{basename}/{Path(doc).name}")
    return expected


def verify_tarball_manifest(tarball: Path,
                            expected: set) -> Tuple[List[str], int]:
    """
    Run `tar -tzf <tarball>`, log every entry to stdout (workflow-log
    manifest visibility), and verify no entry falls outside `expected`.
    Returns (listing, exit_code).  exit_code = 0 on success, 12 on
    unexpected entries.
    """
    banner("Manifest check (tar -tzf)")
    cp = run_noexcept(["tar", "-tzf", str(tarball)])
    if cp.returncode != 0:
        print(f"! tar -tzf failed (exit {cp.returncode}); failing.")
        return [], 12

    listing = [line for line in cp.stdout.splitlines() if line.strip()]
    for entry in listing:
        print(f"    {entry}")

    # tar may also emit an implicit "<basename>/lib/" entry only if a lib
    # directory is non-empty.  An empty lib/ directory should not appear; if
    # the strict gate above produced an empty lib/, the staging step removes
    # it before tarring (see clean_empty_lib_dir below in main()).
    unexpected = [e for e in listing if e not in expected]
    if unexpected:
        print("! Manifest contains unexpected entries (not in allow-set):")
        for u in unexpected:
            print(f"    + {u}")
        print(f"  - expected allow-set ({len(expected)} entries):")
        for e in sorted(expected):
            print(f"    = {e}")
        return listing, 12

    print(f"  - Manifest OK ({len(listing)} entries, all within allow-set).")
    return listing, 0


# -------------------------
# /tmp smoke test
# -------------------------

def smoke_test(exe_path: Path, test_args: List[str], expect_exit: Optional[int], pass_if_stdout_contains: Optional[str]) -> bool:
    banner("Smoke test")
    tmp = Path("/tmp")
    cmd = [str(exe_path)] + test_args
    cp = run_noexcept(cmd, cwd=tmp)

    stdout = cp.stdout or ""
    stderr = cp.stderr or ""

    if stdout.strip():
        print(stdout.rstrip())
    if stderr.strip():
        print(stderr.rstrip(), file=sys.stderr)

    ok = False
    if expect_exit is not None:
        ok = (cp.returncode == expect_exit)
    else:
        # Auto mode:
        # - exit 0 is always success
        # - otherwise, accept success if stdout includes a marker like "Usage:"
        if cp.returncode == 0:
            ok = True
        elif pass_if_stdout_contains and (pass_if_stdout_contains in stdout):
            ok = True

    print(f"\nSMOKE TEST: {'PASS ✅' if ok else 'FAIL ❌'} (exit {cp.returncode})")
    return ok


# -------------------------
# Main
# -------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", type=Path, default=Path.cwd(),
                    help="Project root containing alire.toml")
    ap.add_argument("--bin-name", default=None,
                    help="Executable name under bin/ (auto-detect if omitted)")
    ap.add_argument("--dist-dir", type=Path, default=None,
                    help="Output dist directory (default: <project>/dist)")
    ap.add_argument("--no-build", action="store_true", help="Skip alr build step")
    ap.add_argument("--alire-toolchains", type=Path, default=ALIRE_TOOLCHAINS_DEFAULT,
                    help="Alire toolchains root (default: ~/.local/share/alire/toolchains)")

    # Smoke-test args.
    ap.add_argument("--test-args", default="",
                    help='Args to run in smoke test (default: "")')
    ap.add_argument("--no-test", action="store_true", help="Skip /tmp smoke test")
    ap.add_argument("--expect-exit", type=int, default=None,
                    help="Treat this exit code as success for the smoke test (default: auto)")
    ap.add_argument("--pass-if-stdout-contains", default="Usage:",
                    help='Treat smoke test as success if stdout contains this string (default: "Usage:")')

    ap.add_argument("--codesign", action="store_true", help="macOS only: ad-hoc codesign dist/")

    # Release-packaging flags.
    ap.add_argument("--tarball", required=True, metavar="BASENAME",
                    help="Basename for the produced tarball (e.g. adafmt-1.0.0-rc1-linux-amd64). "
                         "The script stages under dist/<basename>/ and emits "
                         "<project>/<basename>.tar.gz plus <basename>.tar.gz.sha256.")
    ap.add_argument("--include-docs", default="",
                    help="Comma-separated list of project-root files to copy into the staged "
                         "tree (e.g. LICENSE,THIRD_PARTY_LICENSES.md,README.md,CHANGELOG.md). "
                         "Missing files fail (no silent skipping).")
    ap.add_argument("--strict-system-deps", action="store_true",
                    help="Linux only: after bundling, verify the binary's dynamic dependency "
                         "closure matches the ALLOWED_SYSTEM_DEPS allowlist.  Fails on any "
                         "unexpected entry.")

    args = ap.parse_args()

    project = args.project_dir.resolve()
    dist = (args.dist_dir.resolve() if args.dist_dir else (project / "dist"))
    bin_dir = project / "bin"
    basename = args.tarball
    doc_list = [d.strip() for d in args.include_docs.split(",") if d.strip()]

    if not (project / "alire.toml").exists():
        return fail(f"Expected alire.toml in {project}", 2)

    # Build
    if not args.no_build:
        banner("Build")
        cp = run_noexcept(["alr", "build", "--release", "--", "-j0"], cwd=project)
        if cp.stdout.strip():
            print(cp.stdout.rstrip())
        if cp.stderr.strip():
            print(cp.stderr.rstrip(), file=sys.stderr)
        if cp.returncode != 0:
            return fail("Build failed.", 3)
        print("  - Build complete.")

    # Auto-detect bin name if needed
    bin_name = args.bin_name
    if not bin_name:
        detected = detect_single_bin(bin_dir)
        if not detected:
            exes = [p.name for p in sorted(bin_dir.iterdir()) if p.is_file() and is_executable_file(p)] if bin_dir.exists() else []
            return fail(
                "Could not auto-detect a single executable in ./bin.\n"
                f"Found executables: {exes}\n"
                "Please pass --bin-name <name>.",
                4
            )
        bin_name = detected
        print(f"  - Auto-detected binary: {bin_name}")

    src_bin = bin_dir / bin_name
    if not src_bin.exists():
        return fail(f"Binary not found: {src_bin}", 5)

    # Stage under dist/<basename>/ — single layout, no flat-dist legacy mode.
    stage_root = dist / basename
    dist_bin = stage_root / "bin"
    dist_lib = stage_root / "lib"

    banner(f"Stage dist/{basename}/")
    if dist.exists():
        shutil.rmtree(dist)
    ensure_dir(dist_bin)
    ensure_dir(dist_lib)

    dst_bin = dist_bin / bin_name
    copy2_exec(src_bin, dst_bin)
    print(f"  - Copied: {src_bin} -> {dst_bin}")

    sysname = platform.system().lower()

    if sysname == "linux":
        ok, missing = linux_bundle_missing(dst_bin, dist_lib, args.alire_toolchains)
        banner("Final ldd")
        cp = run(["ldd", str(dst_bin)], check=True)
        print(cp.stdout.rstrip())
        if not ok:
            return fail(f"Still missing deps after bundling: {missing}", 6)

        if args.strict_system_deps:
            rc = enforce_strict_system_deps(dst_bin)
            if rc != 0:
                return rc

    elif sysname == "darwin":
        banner("macOS rpath + bundle")
        macos_add_dist_rpath(dst_bin)
        macos_copy_needed_dylibs(dst_bin, dist_lib)
        macos_rewrite_to_rpath(dst_bin, dist_lib)

        banner("Final otool")
        cp = run(["otool", "-L", str(dst_bin)], check=True)
        print(cp.stdout.rstrip())

        if args.codesign:
            macos_codesign_dist(stage_root)

    else:
        return fail(f"Unsupported platform: {platform.system()}", 7)

    # Required docs (fail-on-missing).
    if doc_list:
        rc = include_docs_into_stage(stage_root, project, doc_list)
        if rc != 0:
            return rc

    # Remove empty lib/ directory so the manifest does not list an empty
    # tar entry for it (static-link builds produce no bundled libs).
    bundled_lib_names: List[str] = []
    if dist_lib.is_dir():
        bundled_lib_names = sorted(p.name for p in dist_lib.iterdir() if p.is_file())
        if not bundled_lib_names:
            try:
                dist_lib.rmdir()
                print(f"  - Removed empty staged lib/ directory (no bundled libs).")
            except OSError:
                pass

    # Strip macOS metadata before tarring (no-op on non-Darwin hosts unless
    # someone copied a file with `._*` / `.DS_Store` into the staged tree).
    strip_macos_metadata(stage_root)

    # Smoke test against the staged binary BEFORE tarring so a broken binary
    # short-circuits before producing a release artifact.
    if not args.no_test:
        test_args = args.test_args.split() if args.test_args.strip() else []
        ok = smoke_test(dst_bin, test_args, args.expect_exit, args.pass_if_stdout_contains)
        if not ok:
            return 8

    # Tarball + sha256 + manifest check + log listing.
    tarball, rc = create_tarball(dist, basename, project)
    if rc != 0:
        return rc

    _sha_path, rc = write_sha256(tarball)
    if rc != 0:
        return rc

    expected = expected_manifest_entries(basename, bin_name, doc_list, bundled_lib_names)
    _listing, rc = verify_tarball_manifest(tarball, expected)
    if rc != 0:
        return rc

    banner("DONE ✅")
    print(f"stage:   {stage_root}")
    print(f"tarball: {tarball}")
    print(f"sha256:  {tarball.name}.sha256")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
