#!/usr/bin/env python3
"""
package_dist.py — Build + create relocatable dist/ bundle for an Alire GNAT Ada CLI.

Features:
- Auto-detect binary name from ./bin if exactly one executable (else require --bin-name).
- Auto-run a /tmp smoke test and print PASS/FAIL.
- Linux: bundle only missing shared libs ("=> not found") by searching Alire toolchains.
- macOS: bundle dylibs, rewrite to @rpath, ensure @executable_path/../lib rpath.
- macOS: optional ad-hoc codesign of dist/ via --codesign.
- macOS: always run `install_name_tool -add_rpath @executable_path/../lib dist/bin/<exe>` (harmless if already present).
- Smoke test: supports "usage-style" CLIs that exit non-zero when printing usage.

Default layout:
  project/
    bin/<exe>
    dist/
      bin/<exe>
      lib/(runtime libs)

Usage:
  python3 package_dist.py
  python3 package_dist.py --bin-name adafmt
  python3 package_dist.py --no-build
  python3 package_dist.py --test-args ""               # run with no args (usage output)
  python3 package_dist.py --test-args "--help"         # if your CLI supports it
  python3 package_dist.py --codesign                   # macOS only
  python3 package_dist.py --expect-exit 1              # force expected exit code
  python3 package_dist.py --pass-if-stdout-contains "Usage:"  # auto-pass if output contains substring

Notes:
- Linux relies on: ldd
- macOS relies on: otool, install_name_tool (Xcode CLI tools)
- macOS codesign (optional): codesign
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
    ap.add_argument("--project-dir", type=Path, default=Path.cwd(), help="Project root containing alire.toml")
    ap.add_argument("--bin-name", default=None, help="Executable name under bin/ (auto-detect if omitted)")
    ap.add_argument("--dist-dir", type=Path, default=None, help="Output dist directory (default: <project>/dist)")
    ap.add_argument("--no-build", action="store_true", help="Skip alr build step")
    ap.add_argument("--alire-toolchains", type=Path, default=ALIRE_TOOLCHAINS_DEFAULT,
                    help="Alire toolchains root (default: ~/.local/share/alire/toolchains)")

    # Smoke test defaults updated:
    # - default test args: "" (run with no args)
    # - default pass marker: "Usage:" (treat usage output as success)
    ap.add_argument("--test-args", default="", help='Args to run in smoke test (default: "")')
    ap.add_argument("--no-test", action="store_true", help="Skip /tmp smoke test")
    ap.add_argument("--expect-exit", type=int, default=None,
                    help="Treat this exit code as success for the smoke test (default: auto)")
    ap.add_argument("--pass-if-stdout-contains", default="Usage:",
                    help='Treat smoke test as success if stdout contains this string (default: "Usage:")')

    ap.add_argument("--codesign", action="store_true", help="macOS only: ad-hoc codesign dist/")

    args = ap.parse_args()

    project = args.project_dir.resolve()
    dist = (args.dist_dir.resolve() if args.dist_dir else (project / "dist"))
    bin_dir = project / "bin"

    if not (project / "alire.toml").exists():
        return fail(f"Expected alire.toml in {project}", 2)

    # Build
    if not args.no_build:
        banner("Build")
        # Match your typical command pattern
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

    # Create dist layout + copy binary
    dist_bin = dist / "bin"
    dist_lib = dist / "lib"

    banner("Stage dist/")
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

    elif sysname == "darwin":
        banner("macOS rpath + bundle")

        # Run the exact requested command (harmless if already present):
        macos_add_dist_rpath(dst_bin)

        # Bundle dylibs and rewrite to @rpath
        macos_copy_needed_dylibs(dst_bin, dist_lib)
        macos_rewrite_to_rpath(dst_bin, dist_lib)

        banner("Final otool")
        cp = run(["otool", "-L", str(dst_bin)], check=True)
        print(cp.stdout.rstrip())

        if args.codesign:
            macos_codesign_dist(dist)

    else:
        return fail(f"Unsupported platform: {platform.system()}", 7)

    # Smoke test
    if not args.no_test:
        test_args = args.test_args.split() if args.test_args.strip() else []
        ok = smoke_test(dst_bin, test_args, args.expect_exit, args.pass_if_stdout_contains)
        if not ok:
            return 8

    banner("DONE ✅")
    print(f"dist folder: {dist}")
    if args.test_args.strip():
        print(f"run from anywhere: {dst_bin} {args.test_args}")
    else:
        print(f"run from anywhere: {dst_bin}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
