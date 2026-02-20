#!/usr/bin/env python3
"""
namespace_layers.py - Namespace internal layer packages under project root.

Transforms hybrid_app_ada / hybrid_lib_ada starter projects so internal
layer packages (Domain, Application, Infrastructure, …) become children
of the project root package (<Project>.Domain, <Project>.Application, …).

This prevents GPR compilation-unit name collisions when libraries and
applications are composed, because each project's internal packages
live under a unique namespace.

Usage:
    python3 namespace_layers.py /path/to/hybrid_app_ada
    python3 namespace_layers.py /path/to/hybrid_lib_ada
    python3 namespace_layers.py /path/to/project --dry-run
    python3 namespace_layers.py /path/to/project --verbose

Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
SPDX-License-Identifier: BSD-3-Clause
"""

import argparse
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# ============================================================================
# Constants
# ============================================================================

APP_LAYERS = ["domain", "application", "infrastructure",
              "presentation", "bootstrap"]
LIB_LAYERS = ["domain", "application", "infrastructure"]

LAYER_ADA_NAME: Dict[str, str] = {
    "domain":         "Domain",
    "application":    "Application",
    "infrastructure": "Infrastructure",
    "presentation":   "Presentation",
    "bootstrap":      "Bootstrap",
}

ADA_EXTENSIONS = {".ads", ".adb"}

# Directories to skip during content transformation (submodules, artifacts)
SKIP_DIRS = {"test/python", ".git", "obj", "bin", "lib", "alire", ".alire"}


# ============================================================================
# Helpers
# ============================================================================

def to_ada_pascal(snake: str) -> str:
    """snake_case -> Ada_Pascal_Case  (hybrid_app_ada -> Hybrid_App_Ada)."""
    return "_".join(w.capitalize() for w in snake.split("_"))


def detect_project_type(project_dir: Path) -> str:
    """Return 'app' if src/bootstrap/ exists, else 'lib'."""
    return "app" if (project_dir / "src" / "bootstrap").is_dir() else "lib"


def detect_project_name(project_dir: Path) -> str:
    """Extract crate name from alire.toml (name = "...")."""
    alire = project_dir / "alire.toml"
    if not alire.exists():
        raise FileNotFoundError(f"alire.toml not found in {project_dir}")
    for line in alire.read_text().splitlines():
        m = re.match(r'name\s*=\s*"([^"]+)"', line.strip())
        if m:
            return m.group(1)
    raise ValueError(f"Could not find 'name' in {alire}")


def step_header(n: int, desc: str) -> None:
    print(f"\n{'=' * 64}")
    print(f"  Step {n}: {desc}")
    print(f"{'=' * 64}")


def action(verb: str, detail: str = "") -> None:
    print(f"  {verb:8s} {detail}")


# ============================================================================
# Transformer
# ============================================================================

class NamespaceTransformer:
    """Transform a hybrid starter to namespace layer packages."""

    def __init__(self, project_dir: Path, *,
                 dry_run: bool = False, verbose: bool = False):
        self.root = project_dir.resolve()
        self.dry   = dry_run
        self.verb  = verbose

        self.kind  = detect_project_type(self.root)
        self.name  = detect_project_name(self.root)  # snake_case
        self.ada   = to_ada_pascal(self.name)         # Ada_Pascal_Case
        self.layers = APP_LAYERS if self.kind == "app" else LIB_LAYERS

        self.src   = self.root / "src"
        self.test  = self.root / "test"
        self.examp = self.root / "examples"

        # counters
        self.n_renamed  = 0
        self.n_content  = 0
        self.n_gpr      = 0

    # ------------------------------------------------------------------ run
    def run(self) -> None:
        hdr = (f"\nNamespace Layer Transformation\n{'=' * 64}\n"
               f"  Project : {self.ada}\n"
               f"  Type    : {self.kind}\n"
               f"  Dir     : {self.root}\n"
               f"  Layers  : {', '.join(LAYER_ADA_NAME[l] for l in self.layers)}\n"
               f"  Mode    : {'DRY-RUN' if self.dry else 'LIVE'}\n"
               f"{'=' * 64}")
        print(hdr)

        self._step1_root_dir()
        self._step2_root_gpr()
        self._step3_rename_files()
        self._step4_content()
        self._step5_layer_gprs()
        self._step6_main_gpr()
        self._step7_version_gpr()
        self._step8_test_gprs()
        self._report()

    # --------------------------------------------------------- step 1: root dir
    def _step1_root_dir(self) -> None:
        step_header(1, "Create src/root/ and move root package")

        root_dir = self.src / "root"
        fname    = f"{self.name}.ads"

        if self.kind == "app":
            src_file = self.src / "version" / fname
        else:
            src_file = self.src / fname

        dst_file = root_dir / fname

        if not src_file.exists():
            print(f"  WARNING: root package not found at {src_file}")
            return

        action("MKDIR",  str(root_dir.relative_to(self.root)))
        action("MOVE",   f"{src_file.relative_to(self.root)} -> "
                         f"{dst_file.relative_to(self.root)}")

        if not self.dry:
            root_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src_file), str(dst_file))

    # --------------------------------------------------------- step 2: root.gpr
    def _step2_root_gpr(self) -> None:
        step_header(2, "Create root.gpr project file")

        gpr_path = self.src / "root" / "root.gpr"
        shared   = f"{self.name}_shared_config"
        shared_ada = to_ada_pascal(shared)

        body = (
            f"-- ================================================================\n"
            f"-- Root GPR - Project Root Package\n"
            f"-- ================================================================\n"
            f"-- Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.\n"
            f"-- SPDX-License-Identifier: BSD-3-Clause\n"
            f"--\n"
            f"-- Purpose:\n"
            f"--   Provides the project root package ({self.ada}) so that all\n"
            f"--   layer GPR projects can compile their child packages.\n"
            f"-- ================================================================\n"
            f"\n"
            f'with "../../{shared}.gpr";\n'
            f"\n"
            f"library project Root is\n"
            f"\n"
            f'   for Source_Dirs use (".");\n'
            f'   for Object_Dir use "../../obj/root";\n'
            f'   for Library_Dir use "../../lib/root";\n'
            f'   for Library_Name use "root";\n'
            f'   for Library_Kind use "static";\n'
            f'   for Create_Missing_Dirs use "True";\n'
            f"\n"
            f'   for Library_Standalone use "standard";\n'
            f"\n"
            f"   for Library_Interface use\n"
            f'     ("{self.ada}");\n'
            f"\n"
            f"   package Compiler renames {shared_ada}.Compiler;\n"
            f"   package Binder renames {shared_ada}.Binder;\n"
            f"\n"
            f"end Root;\n"
        )

        action("CREATE", str(gpr_path.relative_to(self.root)))
        if not self.dry:
            gpr_path.parent.mkdir(parents=True, exist_ok=True)
            gpr_path.write_text(body)

    # --------------------------------------------------------- step 3: rename
    def _step3_rename_files(self) -> None:
        step_header(3, "Rename Ada source files with project prefix")

        for layer in self.layers:
            layer_dir = self.src / layer
            if not layer_dir.is_dir():
                continue
            print(f"\n  Layer: {LAYER_ADA_NAME[layer]}")

            targets: List[Tuple[Path, Path]] = []
            for ext in sorted(ADA_EXTENSIONS):
                for fp in sorted(layer_dir.rglob(f"*{ext}")):
                    nm = fp.name
                    if nm == f"{layer}{ext}" or nm.startswith(f"{layer}-"):
                        new = fp.parent / f"{self.name}-{nm}"
                        targets.append((fp, new))

            for old, new in targets:
                action("RENAME", f"{old.relative_to(self.root)} -> {new.name}")
                if not self.dry:
                    old.rename(new)
                self.n_renamed += 1

    # --------------------------------------------------------- step 4: content
    def _step4_content(self) -> None:
        step_header(4, "Update Ada source content "
                       "(with / use / package / end / qualified refs)")

        dirs = [self.src]
        if self.test.is_dir():
            dirs.append(self.test)
        if self.examp.is_dir():
            dirs.append(self.examp)

        for d in dirs:
            for ext in sorted(ADA_EXTENSIONS):
                for fp in sorted(d.rglob(f"*{ext}")):
                    if not self._in_skip_dir(fp):
                        self._transform_file(fp)

    def _in_skip_dir(self, fp: Path) -> bool:
        """Return True if fp is inside a directory that should be skipped."""
        rel = fp.relative_to(self.root)
        for skip in SKIP_DIRS:
            if str(rel).startswith(skip + os.sep) or str(rel).startswith(skip + "/"):
                return True
        return False

    def _transform_file(self, fp: Path) -> None:
        orig = fp.read_text()
        xfrm = self._ns(orig)
        if xfrm == orig:
            return
        action("UPDATE", str(fp.relative_to(self.root)))
        if self.verb:
            for i, (a, b) in enumerate(
                    zip(orig.splitlines(), xfrm.splitlines()), 1):
                if a != b:
                    print(f"      L{i}: {a.strip()}")
                    print(f"        -> {b.strip()}")
        if not self.dry:
            fp.write_text(xfrm)
        self.n_content += 1

    def _ns(self, txt: str) -> str:
        """Add project prefix to bare layer references."""
        for layer in self.layers:
            ada = LAYER_ADA_NAME[layer]
            # Match bare layer name not preceded by dot / word-char
            # and not followed by underscore / word-char / hyphen.
            # Prevents: My_Domain, Hybrid_App_Ada.Domain, Application-level
            pat = rf'(?<![.\w])({re.escape(ada)})(?![_\w\-])'
            txt = re.sub(pat, rf'{self.ada}.\1', txt)
        return txt

    # ------------------------------------------------- step 5: layer GPRs
    def _step5_layer_gprs(self) -> None:
        step_header(5, "Update layer GPR files "
                       "(root dependency + Library_Interface)")

        for layer in self.layers:
            gpr = self.src / layer / f"{layer}.gpr"
            if not gpr.exists():
                continue
            print(f"\n  {gpr.relative_to(self.root)}")

            txt = gpr.read_text()
            orig = txt

            txt = self._inject_root_with(txt)
            txt = self._ns_library_interface(txt)

            if txt != orig:
                action("UPDATE", str(gpr.relative_to(self.root)))
                if not self.dry:
                    gpr.write_text(txt)
                self.n_gpr += 1

    # ------------------------------------------------- step 6: main GPR
    def _step6_main_gpr(self) -> None:
        step_header(6, "Update main project GPR")
        gpr = self.root / f"{self.name}.gpr"
        if not gpr.exists():
            print(f"  Not found: {gpr.name}")
            return

        txt = gpr.read_text()
        orig = txt

        if self.kind == "lib":
            txt = self._ns_library_interface(txt)
            # Upgrade to encapsulated for the external-facing library
            txt = txt.replace(
                'for Library_Standalone use "standard"',
                'for Library_Standalone use "encapsulated"')
        # App aggregate has no Library_Interface

        if txt != orig:
            action("UPDATE", gpr.name)
            if not self.dry:
                gpr.write_text(txt)
            self.n_gpr += 1

    # ------------------------------------------------- step 7: version GPR
    def _step7_version_gpr(self) -> None:
        step_header(7, "Update version.gpr")
        gpr = self.src / "version" / "version.gpr"
        if not gpr.exists():
            print("  Not found.")
            return

        txt = gpr.read_text()
        orig = txt

        txt = self._inject_root_with(txt)

        # App project: root package was in version dir, now in root dir.
        # Remove bare root entry from version.gpr Library_Interface.
        if self.kind == "app":
            # Match:  "Hybrid_App_Ada",\n  <whitespace>  "
            # and collapse to just "
            pat = rf'"{re.escape(self.ada)}",\s*\n\s*"'
            txt = re.sub(pat, '"', txt)

        if txt != orig:
            action("UPDATE", str(gpr.relative_to(self.root)))
            if not self.dry:
                gpr.write_text(txt)
            self.n_gpr += 1

    # ------------------------------------------------- step 8: test GPRs
    def _step8_test_gprs(self) -> None:
        step_header(8, "Update test GPR files (add root.gpr dependency)")

        if not self.test.is_dir():
            print("  No test directory.")
            return

        for gpr in sorted(self.test.rglob("*.gpr")):
            # Skip config GPR files and submodule directories
            if "_config" in gpr.name or self._in_skip_dir(gpr):
                continue
            txt = gpr.read_text()
            orig = txt

            # Compute relative path from this GPR to src/root/root.gpr
            rel = os.path.relpath(self.src / "root" / "root.gpr",
                                  gpr.parent)
            with_line = f'with "{rel}";'

            if with_line not in txt and "root.gpr" not in txt:
                txt = self._inject_with_line(txt, with_line)

            if txt != orig:
                action("UPDATE", str(gpr.relative_to(self.root)))
                if not self.dry:
                    gpr.write_text(txt)
                self.n_gpr += 1

    # ---------------------------------------------------------------- report
    def _report(self) -> None:
        label = "PREVIEW" if self.dry else "COMPLETE"
        print(f"\n{'=' * 64}")
        print(f"  TRANSFORMATION {label}")
        print(f"{'=' * 64}")
        print(f"  Files renamed  : {self.n_renamed}")
        print(f"  Files modified : {self.n_content}")
        print(f"  GPRs modified  : {self.n_gpr}")
        if self.dry:
            print(f"\n  DRY-RUN — no files were changed.")
            print(f"  Re-run without --dry-run to apply.")
        print(f"{'=' * 64}\n")

    # ====================================================================
    # GPR manipulation helpers
    # ====================================================================

    def _inject_root_with(self, txt: str) -> str:
        """Insert  with "../root/root.gpr";  after the last existing with."""
        marker = 'with "../root/root.gpr";'
        if marker in txt:
            return txt
        return self._inject_with_line(txt, marker)

    @staticmethod
    def _inject_with_line(txt: str, line: str) -> str:
        """Insert a 'with' line after the last existing 'with' statement."""
        lines = txt.splitlines(True)
        last_idx = -1
        for i, ln in enumerate(lines):
            s = ln.strip()
            if s.startswith("with ") and s.endswith(";"):
                last_idx = i
        if last_idx >= 0:
            lines.insert(last_idx + 1, line + "\n")
        else:
            # No with lines — insert before first non-comment line
            for i, ln in enumerate(lines):
                s = ln.strip()
                if s and not s.startswith("--"):
                    lines.insert(i, line + "\n")
                    break
        return "".join(lines)

    def _ns_library_interface(self, txt: str) -> str:
        """Namespace package names inside Library_Interface strings."""
        for layer in self.layers:
            ada = LAYER_ADA_NAME[layer]
            # "Domain" -> "Hybrid_App_Ada.Domain"
            # "Domain.Error" -> "Hybrid_App_Ada.Domain.Error"
            pat  = rf'"({re.escape(ada)})([".])'
            repl = rf'"{self.ada}.\1\2'
            txt  = re.sub(pat, repl, txt)
        return txt


# ============================================================================
# CLI
# ============================================================================

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Namespace internal layer packages under project root.")
    ap.add_argument("project_dir", type=Path,
                    help="Path to hybrid project to transform")
    ap.add_argument("--dry-run", action="store_true",
                    help="Preview without modifying files")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="Show line-level changes")
    args = ap.parse_args()

    d = args.project_dir.resolve()
    if not d.is_dir():
        sys.exit(f"Error: not a directory: {d}")
    if not (d / "alire.toml").exists():
        sys.exit(f"Error: no alire.toml in {d}")

    NamespaceTransformer(d, dry_run=args.dry_run,
                         verbose=args.verbose).run()


if __name__ == "__main__":
    main()
