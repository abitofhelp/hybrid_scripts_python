#!/usr/bin/env python3
# ==============================================================================
# compile_formal_docs.py
# ==============================================================================
# Copyright (c) 2025 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE file in the project root.
#
# Purpose:
#   Compiles Typst formal documents (SRS, SDS, STG) to PDF by colocating
#       project-specific .typ sources with shared templates in a temporary
#       directory, then running the Typst compiler. This avoids symlinks,
#       extra gitmodules, or cross-repo linking.
#
# Usage:
#   From a project root:
#       python3 scripts/python/shared/makefile/compile_formal_docs.py
#
#   From a Makefile:
#       docs-formal:
#           @python3 scripts/python/shared/makefile/compile_formal_docs.py
#
#   With explicit paths:
#       python3 compile_formal_docs.py \
#           --project-dir /path/to/project \
#           --templates-dir /path/to/Shared_Docs/templates/formal
#
# Design Notes:
#   The Typst formal docs use #import "core.typ" which requires core.typ
#       to be in the same directory at compile time. Rather than maintaining
#       symlinks or gitmodule mounts, this script creates a temporary working
#       directory, copies the shared templates and project sources into it,
#       compiles each document, and writes the PDFs to the project's
#       docs/formal/ directory. The temporary directory is always cleaned up.
#
# See Also:
#   /Users/mike/Shared_Docs/templates/formal/ - shared Typst templates
#   docs/formal/ - project-specific formal document sources and PDFs
# ==============================================================================

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Default path to shared Typst templates.
DEFAULT_TEMPLATES_DIR = Path.home() / "Shared_Docs" / "templates" / "formal"

# Shared template files to copy into the build directory.
SHARED_TEMPLATES = ["core.typ", "utility.typ"]

# Project formal doc sources are any .typ files in docs/formal/ that are
# not shared templates.
FORMAL_DOCS_SUBDIR = Path("docs") / "formal"


def find_project_root(start: Path) -> Path | None:
    """
    Walk upward from start to find the project root (contains docs/formal/).

    Args:
        start: Directory to start searching from.

    Returns:
        The project root path, or None if not found.
    """
    current = start.resolve()
    for _ in range(10):
        if (current / FORMAL_DOCS_SUBDIR).is_dir():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def compile_formal_docs(
    project_dir: Path,
    templates_dir: Path,
    dry_run: bool = False,
) -> int:
    """
    Compile all Typst formal documents in a project to PDF.

    Args:
        project_dir: Project root directory.
        templates_dir: Directory containing shared Typst templates.
        dry_run: If True, show what would be done without compiling.

    Returns:
        0 on success, 1 on failure.
    """
    formal_dir = project_dir / FORMAL_DOCS_SUBDIR

    if not formal_dir.is_dir():
        print(f"ERROR: The formal docs directory does not exist: {formal_dir}",
              file=sys.stderr)
        return 1

    if not templates_dir.is_dir():
        print(f"ERROR: The templates directory does not exist: {templates_dir}",
              file=sys.stderr)
        return 1

    # Find project .typ sources (exclude shared templates by name).
    shared_names = set(SHARED_TEMPLATES)
    project_sources = sorted(
        p for p in formal_dir.glob("*.typ")
        if p.name not in shared_names
    )

    if not project_sources:
        print("No .typ formal documents were found to compile.")
        return 0

    print(f"Project: {project_dir.name}")
    print(f"Templates: {templates_dir}")
    print(f"Documents: {len(project_sources)}")
    for src in project_sources:
        print(f"  - {src.name}")
    print()

    if dry_run:
        for src in project_sources:
            pdf_name = src.with_suffix(".pdf").name
            print(f"  [dry-run] Would compile {src.name} -> {formal_dir / pdf_name}")
        return 0

    # Create temporary build directory, compile, clean up.
    with tempfile.TemporaryDirectory(prefix="typst_build_") as tmp:
        tmp_dir = Path(tmp)

        # Copy shared templates into the build directory.
        for template_name in SHARED_TEMPLATES:
            src_path = templates_dir / template_name
            if src_path.is_file():
                shutil.copy2(src_path, tmp_dir / template_name)

        # Copy project .typ sources into the build directory.
        for src in project_sources:
            shutil.copy2(src, tmp_dir / src.name)

        # Compile each document.
        succeeded = 0
        failed = 0

        for src in project_sources:
            typ_path = tmp_dir / src.name
            pdf_name = src.with_suffix(".pdf").name
            pdf_path = formal_dir / pdf_name

            result = subprocess.run(
                ["typst", "compile", str(typ_path), str(pdf_path)],
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                print(f"  OK: {src.name} -> {pdf_name}")
                succeeded += 1
            else:
                print(f"  FAILED: {src.name}", file=sys.stderr)
                if result.stderr:
                    print(result.stderr.rstrip(), file=sys.stderr)
                failed += 1

        print(f"\nDone. {succeeded} succeeded, {failed} failed.")
        return 1 if failed > 0 else 0


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments.

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Compile Typst formal documents (SRS, SDS, STG) to PDF.",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help="Project root directory (auto-detected if omitted).",
    )
    parser.add_argument(
        "--templates-dir",
        type=Path,
        default=DEFAULT_TEMPLATES_DIR,
        help=f"Shared Typst templates directory (default: {DEFAULT_TEMPLATES_DIR}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without compiling.",
    )
    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()

    if args.project_dir is not None:
        project_dir = args.project_dir.resolve()
    else:
        project_dir = find_project_root(Path.cwd())
        if project_dir is None:
            print("ERROR: Could not find a project root with docs/formal/. "
                  "Run from a project directory or use --project-dir.",
                  file=sys.stderr)
            return 1

    if not shutil.which("typst"):
        print("ERROR: The typst compiler was not found in PATH.", file=sys.stderr)
        return 1

    return compile_formal_docs(project_dir, args.templates_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
