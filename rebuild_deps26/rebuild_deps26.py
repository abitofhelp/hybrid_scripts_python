#!/usr/bin/env python3
# ==============================================================================
# rebuild_deps26.py - Clean and rebuild deps26 libraries from source
# ==============================================================================
# Copyright (c) 2025 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE file in the project root.
#
# Purpose:
#   Rebuilds the AdaCore 26.0 dependency libraries (deps26/) from source for
#   the current architecture. Required because the Alire crates for these
#   libraries have a gnatcoll/GNAT runtime incompatibility (timeval issue).
#   See astfmt/alire.toml for full details.
#
# Usage:
#   python3 -m rebuild_deps26 [OPTIONS]
#
#   Options:
#     --deps-dir DIR   Path to deps26 directory (default: /workspace/deps26)
#     --jobs N         Parallel compilation jobs (default: 0 = all cores)
#     --clean          Clean object dirs before building
#     --clean-only     Only clean, do not build
#     --dry-run        Show what would be done without executing
#     --verbose        Print detailed build output
#
#   Exit Codes:
#     0: All libraries built successfully
#     1: One or more builds failed
#     2: Script error (missing deps dir, missing tools, etc.)
#
# Build Order (respects dependency chain):
#   1.  gprconfig_kb      - no build needed (data-only, no .gpr)
#   2.  AdaSAT            - standalone, no deps26 dependencies
#   3.  gnatcoll-core     - built WITHOUT gnatcoll_projects (needs libgpr2)
#   4.  gnatcoll-gmp      - depends on gnatcoll-core (gnatcoll_minimal)
#   5.  gnatcoll-iconv    - depends on gnatcoll-core
#   6.  prettier-ada      - depends on vss_text (from Alire, not deps26)
#   7.  libgpr2           - depends on gnatcoll, gprconfig_kb
#   8.  gnatcoll-projects - depends on libgpr2 (built after libgpr2)
#   9.  langkit/support   - depends on gnatcoll, adasat, prettier-ada
#   10. libadalang        - depends on all of the above
#
# Note:
#   VSS (vss_text) is resolved from Alire crates and is NOT in deps26.
#
# See Also:
#   astfmt/alire.toml - documents why deps26 is needed and when it can be dropped
# ==============================================================================

import argparse
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from common import (
    Colors, print_success, print_error, print_warning, print_info,
)


def _print_banner(msg: str) -> None:
    """Print a prominent section banner."""
    print(f"\n{Colors.BLUE}{Colors.BOLD}{'=' * 60}{Colors.NC}")
    print(f"{Colors.BLUE}{Colors.BOLD}  {msg}{Colors.NC}")
    print(f"{Colors.BLUE}{Colors.BOLD}{'=' * 60}{Colors.NC}")


@dataclass
class DepSpec:
    """Specification for a single deps26 library to build."""
    name: str
    subdir: str
    gpr_file: Optional[str]
    clean_dirs: list[str]
    build_cmd: Optional[list[str]]  # None means no build needed


def get_arch() -> str:
    """Return the current machine architecture."""
    machine = platform.machine().lower()
    if machine in ('aarch64', 'arm64'):
        return 'aarch64'
    elif machine in ('x86_64', 'amd64'):
        return 'x86_64'
    return machine


def find_obj_dirs(base: Path) -> list[Path]:
    """Find all obj/ directories under a path."""
    return sorted(base.rglob('obj'))


def clean_dep(deps_dir: Path, spec: DepSpec, verbose: bool = False) -> bool:
    """Clean build artifacts for a dependency."""
    dep_path = deps_dir / spec.subdir
    if not dep_path.exists():
        print_warning(f"Directory not found: {dep_path}")
        return True

    cleaned = False
    for rel_dir in spec.clean_dirs:
        target = dep_path / rel_dir
        if target.exists():
            if verbose:
                print_info(f"Removing {target}")
            shutil.rmtree(target)
            cleaned = True

    # Also clean any obj/ dirs not explicitly listed
    for obj_dir in find_obj_dirs(dep_path):
        if obj_dir.exists():
            if verbose:
                print_info(f"Removing {obj_dir}")
            shutil.rmtree(obj_dir)
            cleaned = True

    # Clean lib/ dirs
    for lib_dir in sorted(dep_path.rglob('lib')):
        if lib_dir.is_dir() and not any(p.name == 'src' for p in lib_dir.parents):
            if verbose:
                print_info(f"Removing {lib_dir}")
            shutil.rmtree(lib_dir)
            cleaned = True

    if cleaned:
        print_success(f"Cleaned {spec.name}")
    else:
        print_info(f"Nothing to clean for {spec.name}")
    return True


def make_build_env(deps_dir: Path) -> dict:
    """
    Create the environment for building deps26 libraries.

    Sets GPR_PROJECT_PATH so that libraries built earlier in the sequence
    (e.g., gnatcoll_minimal, gnatcoll_core) are visible to later ones
    (e.g., gnatcoll_gmp, gnatcoll_iconv, libgpr2).
    """
    import os
    env = os.environ.copy()

    # gnatcoll-core's Makefile installs .gpr files here
    gnatcoll_install = deps_dir / "gnatcoll-core-26.0.0" / "gnatcoll-core-install" / "share" / "gpr"
    # Also add the source dirs for projects that don't use make install
    gnatcoll_minimal = deps_dir / "gnatcoll-core-26.0.0" / "minimal"
    gnatcoll_core = deps_dir / "gnatcoll-core-26.0.0" / "core"

    # gnatcoll bindings need to find each other and gnatcoll_core
    gnatcoll_gmp = deps_dir / "gnatcoll-bindings-26.0.0" / "gmp"
    gnatcoll_iconv = deps_dir / "gnatcoll-bindings-26.0.0" / "iconv"

    # libgpr (gpr.gpr) is needed by gnatcoll_projects
    libgpr_cache = deps_dir / "gpr-26.0.0" / "alire" / "cache" / "dependencies"
    libgpr_dir = None
    if libgpr_cache.exists():
        for d in sorted(libgpr_cache.glob("libgpr_*")):
            gpr_subdir = d / "gpr"
            if (gpr_subdir / "gpr.gpr").exists():
                libgpr_dir = gpr_subdir
                break

    gnatcoll_projects = deps_dir / "gnatcoll-core-26.0.0" / "projects"
    # libgpr2's own project dir
    libgpr2_dir = deps_dir / "gpr-26.0.0"

    # AdaSAT and prettier-ada are needed by langkit-support and libadalang
    adasat_dir = deps_dir / "AdaSAT-26.0.0"
    prettier_ada_dir = deps_dir / "prettier-ada-26.0.0"

    # langkit-support dir (needed by libadalang)
    langkit_support_dir = deps_dir / "langkit-26.0.0" / "langkit" / "support"

    gpr_paths = [
        str(gnatcoll_install),
        str(gnatcoll_minimal),
        str(gnatcoll_core),
        str(gnatcoll_gmp),
        str(gnatcoll_iconv),
        str(gnatcoll_projects),
        str(libgpr2_dir),
        str(adasat_dir),
        str(prettier_ada_dir),
        str(langkit_support_dir),
    ]
    if libgpr_dir:
        gpr_paths.append(str(libgpr_dir))

    # Find vss_text from Alire releases (not in deps26 — fetched as a crate)
    alire_releases = Path.home() / ".local" / "share" / "alire" / "releases"
    if alire_releases.exists():
        for vss_dir in sorted(alire_releases.glob("vss_text_*")):
            gnat_dir = vss_dir / "gnat"
            if (gnat_dir / "vss_text.gpr").exists():
                gpr_paths.append(str(gnat_dir))
                break

    # xmlada: look in gpr-26.0.0's alire cache (needs ./configure first)
    xmlada_cache = deps_dir / "gpr-26.0.0" / "alire" / "cache" / "dependencies"
    if xmlada_cache.exists():
        for xmlada_dir in sorted(xmlada_cache.glob("xmlada_*")):
            shared_gpr = xmlada_dir / "xmlada_shared.gpr"
            configure = xmlada_dir / "configure"
            # Run configure if xmlada_shared.gpr is missing
            if not shared_gpr.exists() and configure.exists():
                subprocess.run(
                    ["./configure"],
                    cwd=str(xmlada_dir),
                    capture_output=True,
                    timeout=120,
                )
            # distrib/xmlada.gpr is the non-aggregate wrapper — it MUST appear
            # before the root xmlada.gpr (which is an aggregate and cannot be
            # imported by non-aggregate projects).
            for subdir in ["distrib", "unicode", "sax", "input_sources",
                           "dom", "schema"]:
                sub_path = xmlada_dir / subdir
                if sub_path.exists():
                    gpr_paths.append(str(sub_path))
            break

    existing = env.get('GPR_PROJECT_PATH', '')
    if existing:
        gpr_paths.append(existing)
    env['GPR_PROJECT_PATH'] = ':'.join(gpr_paths)

    # FIXME: Set timeval arch overrides for aarch64 builds where GNAT 13.x
    # lacks GNAT.Calendar.timeval and GNAT.Sockets.Thin_Common.Timeval.
    # - GNATCOLL_TIMEVAL_ARCH: selects aarch64 body in gnatcoll_core.gpr
    # - GPR_TIMEVAL_ARCH: selects aarch64 body in gpr.gpr (libgpr 25.0.0)
    # REMOVE WHEN: Ubuntu ships GNAT >= 15.2.0 (apt show gnat), or
    # gnatcoll-core/libgpr upstream drop the timeval dependencies.
    if get_arch() == 'aarch64':
        env['GNATCOLL_TIMEVAL_ARCH'] = 'aarch64'
        env['GPR_TIMEVAL_ARCH'] = 'aarch64'

    return env


def build_dep(deps_dir: Path, spec: DepSpec, jobs: int,
              env: dict, verbose: bool = False,
              dry_run: bool = False) -> bool:
    """Build a single dependency. Returns True on success."""
    if spec.build_cmd is None:
        print_info(f"Skipping {spec.name} (no build needed)")
        return True

    dep_path = deps_dir / spec.subdir
    if not dep_path.exists():
        print_error(f"Directory not found: {dep_path}")
        return False

    # Substitute placeholders in build command
    cmd = [
        arg.replace('{jobs}', str(jobs)).replace('{deps_dir}', str(deps_dir))
        for arg in spec.build_cmd
    ]

    print_info(f"Building {spec.name}...")
    if verbose or dry_run:
        print_info(f"  cwd: {dep_path}")
        print_info(f"  cmd: {' '.join(cmd)}")

    if dry_run:
        return True

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(dep_path),
            capture_output=not verbose,
            text=True,
            timeout=600,
            env=env,
        )
        elapsed = time.time() - start

        if result.returncode == 0:
            print_success(f"Built {spec.name} ({elapsed:.1f}s)")
            return True
        else:
            print_error(f"Failed to build {spec.name} (exit {result.returncode})")
            if not verbose and result.stderr:
                # Show last 20 lines of stderr
                lines = result.stderr.strip().split('\n')
                for line in lines[-20:]:
                    print(f"    {line}", file=sys.stderr)
            return False

    except subprocess.TimeoutExpired:
        print_error(f"Build of {spec.name} timed out (600s)")
        return False
    except Exception as e:
        print_error(f"Error building {spec.name}: {e}")
        return False


def get_dep_specs() -> list[DepSpec]:
    """
    Return the ordered list of deps26 libraries to build.

    Order matters: each library is built after its dependencies.
    """
    return [
        DepSpec(
            name="gprconfig_kb",
            subdir="gprconfig_kb-26.0.0",
            gpr_file=None,
            clean_dirs=[],
            build_cmd=None,  # Data-only package, no compilation needed
        ),
        DepSpec(
            name="AdaSAT",
            subdir="AdaSAT-26.0.0",
            gpr_file="adasat.gpr",
            clean_dirs=["obj", "lib"],
            build_cmd=[
                "gprbuild", "-p", "-j{jobs}",
                "-P", "adasat.gpr",
                "-XLIBRARY_TYPE=static",
                "-XBUILD_MODE=dev",
            ],
        ),
        DepSpec(
            name="gnatcoll-core",
            subdir="gnatcoll-core-26.0.0",
            gpr_file="gnatcoll.gpr",
            clean_dirs=["gnatcoll-core-install", "obj", "lib"],
            # Build WITHOUT gnatcoll_projects first — it depends on libgpr2
            # which hasn't been built yet. gnatcoll_projects is built later
            # as a separate step after libgpr2.
            # FIXME: GNATCOLL_TIMEVAL_ARCH=aarch64 selects an alternate body
            # for Wait_For_Processes that uses System.C_Time instead of
            # GNAT.Calendar.timeval (missing in GNAT 13.x).
            # REMOVE WHEN: Ubuntu ships GNAT >= 15.2.0 (apt show gnat), or
            # gnatcoll-core upstream drops the GNAT.Calendar.timeval dependency.
            build_cmd=[
                "make", "build", "PROCESSORS={jobs}",
                "GNATCOLL_PROJECTS=no",
            ],
        ),
        DepSpec(
            name="gnatcoll-gmp",
            subdir="gnatcoll-bindings-26.0.0/gmp",
            gpr_file="gnatcoll_gmp.gpr",
            clean_dirs=["obj", "lib"],
            build_cmd=[
                "gprbuild", "-p", "-j{jobs}",
                "-P", "gnatcoll_gmp.gpr",
                "-XLIBRARY_TYPE=static",
                "-XBUILD_MODE=dev",
            ],
        ),
        DepSpec(
            name="gnatcoll-iconv",
            subdir="gnatcoll-bindings-26.0.0/iconv",
            gpr_file="gnatcoll_iconv.gpr",
            clean_dirs=["obj", "lib"],
            # On Linux, iconv is part of glibc — no separate -liconv needed.
            # GNATCOLL_ICONV_OPT="" prevents the default "-liconv" linker flag.
            build_cmd=[
                "gprbuild", "-p", "-j{jobs}",
                "-P", "gnatcoll_iconv.gpr",
                "-XLIBRARY_TYPE=static",
                "-XBUILD_MODE=dev",
                "-XGNATCOLL_ICONV_OPT=",
            ],
        ),
        DepSpec(
            name="prettier-ada",
            subdir="prettier-ada-26.0.0",
            gpr_file="prettier_ada.gpr",
            clean_dirs=["obj", "lib"],
            build_cmd=[
                "gprbuild", "-p", "-j{jobs}",
                "-P", "prettier_ada.gpr",
                "-XLIBRARY_TYPE=static",
                "-XPRETTIER_ADA_LIBRARY_TYPE=static",
                "-XPRETTIER_ADA_BUILD_MODE=dev",
            ],
        ),
        DepSpec(
            name="libgpr2",
            subdir="gpr-26.0.0",
            gpr_file="gpr2.gpr",
            clean_dirs=[".build", "obj", "lib"],
            build_cmd=[
                "make", "build-libs", "PROCESSORS={jobs}",
                "GPR2KBDIR={deps_dir}/gprconfig_kb-26.0.0/db",
                "ENABLE_SHARED=no",
            ],
        ),
        DepSpec(
            name="gnatcoll-projects",
            subdir="gnatcoll-core-26.0.0/projects",
            gpr_file="gnatcoll_projects.gpr",
            clean_dirs=[],  # Don't clean — gnatcoll-core already built
            # Build gnatcoll_projects directly now that libgpr2 is available
            build_cmd=[
                "gprbuild", "-p", "-j{jobs}",
                "-P", "gnatcoll_projects.gpr",
                "-XLIBRARY_TYPE=static",
                "-XBUILD_MODE=dev",
            ],
        ),
        DepSpec(
            name="langkit-support",
            subdir="langkit-26.0.0/langkit/support",
            gpr_file="langkit_support.gpr",
            clean_dirs=["obj", "lib"],
            build_cmd=[
                "gprbuild", "-p", "-j{jobs}",
                "-P", "langkit_support.gpr",
                "-XLIBRARY_TYPE=static",
                "-XBUILD_MODE=dev",
            ],
        ),
        DepSpec(
            name="libadalang",
            subdir="libadalang-26.0.0",
            gpr_file="libadalang.gpr",
            clean_dirs=["obj", "lib"],
            build_cmd=[
                "gprbuild", "-p", "-j{jobs}",
                "-P", "libadalang.gpr",
                "-XLIBRARY_TYPE=static",
                "-XBUILD_MODE=dev",
            ],
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clean and rebuild deps26 libraries for the current architecture.",
        epilog="Run inside the dev container where GNAT is available.",
    )
    parser.add_argument(
        "--deps-dir",
        type=Path,
        default=Path("/workspace/deps26"),
        help="Path to deps26 directory (default: /workspace/deps26)",
    )
    parser.add_argument(
        "--jobs", "-j",
        type=int,
        default=0,
        help="Parallel compilation jobs (default: 0 = all cores)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean object dirs before building",
    )
    parser.add_argument(
        "--clean-only",
        action="store_true",
        help="Only clean, do not build",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Show what would be done without executing",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print detailed build output",
    )
    args = parser.parse_args()

    # Validate deps directory
    if not args.deps_dir.exists():
        print_error(f"deps26 directory not found: {args.deps_dir}")
        return 2

    # Check for gprbuild
    if not shutil.which("gprbuild"):
        print_error("gprbuild not found in PATH. Run inside the dev container.")
        return 2

    arch = get_arch()
    _print_banner(f"deps26 rebuild for {arch}")

    if args.dry_run:
        print_warning("DRY RUN - no commands will be executed")

    specs = get_dep_specs()

    # Clean phase
    if args.clean or args.clean_only:
        _print_banner("Cleaning build artifacts")
        for spec in specs:
            clean_dep(args.deps_dir, spec, verbose=args.verbose)
        if args.clean_only:
            print_success("Clean complete")
            return 0

    # Build phase
    _print_banner(f"Building {len(specs)} libraries (jobs={args.jobs})")
    env = make_build_env(args.deps_dir)
    failed = []
    for i, spec in enumerate(specs, 1):
        print(f"\n{Colors.BOLD}[{i}/{len(specs)}] {spec.name}{Colors.NC}")
        if not build_dep(args.deps_dir, spec, args.jobs, env=env,
                         verbose=args.verbose, dry_run=args.dry_run):
            failed.append(spec.name)
            print_error(f"Stopping: {spec.name} failed (later deps depend on it)")
            break

    # Summary
    _print_banner("Summary")
    print_info(f"Architecture: {arch}")
    print_info(f"deps26 dir:   {args.deps_dir}")
    if failed:
        print_error(f"FAILED: {', '.join(failed)}")
        return 1
    else:
        print_success("All libraries built successfully")
        return 0


if __name__ == '__main__':
    sys.exit(main())
