#!/usr/bin/env python3
# ==============================================================================
# compile_guides.py
# ==============================================================================
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE file in the project root.
#
# Purpose:
#   Compiles Typst developer-guide documents in docs/guides/ to PDF by
#   colocating project-specific .typ sources with shared guide templates
#   in a temporary directory, then running the Typst compiler. This is a
#   sibling of compile_formal_docs.py but targets docs/guides/ and
#   ~/shared_docs/templates/guides/ instead of docs/formal/ and
#   ~/shared_docs/templates/formal/.
#
# Usage:
#   From a project root:
#       python3 scripts/python/shared/makefile/compile_guides.py
#
#   From a Makefile:
#       docs-guides:
#           @python3 scripts/python/shared/makefile/compile_guides.py
#
#   With explicit paths:
#       python3 compile_guides.py \
#           --project-dir /path/to/project \
#           --templates-dir /path/to/shared_docs/templates/guides
#
# Design Notes:
#   Mirrors compile_formal_docs.py design (same temp-dir strategy) to
#   avoid symlinks or extra gitmodules. The core.typ shared with all
#   guide sources is copied into the temp build directory alongside
#   project .typ sources. Output PDFs land in docs/guides/ next to
#   their sources.
#
#   Keeping this as a sibling (rather than parameterizing
#   compile_formal_docs.py) preserves a dedicated entry point for
#   each document class, so a breakage in one path cannot silently
#   take down the other. Shared logic can be refactored later if
#   churn justifies it.
#
# See Also:
#   compile_formal_docs.py — formal-doc sibling.
#   ~/shared_docs/templates/guides/ — shared Typst guide templates.
#   docs/guides/ — project-specific guide sources and rendered PDFs.
# ==============================================================================

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Default path to shared Typst templates for guides.
DEFAULT_TEMPLATES_DIR = Path.home() / "shared_docs" / "templates" / "guides"

# Shared template files to copy into the build directory.
SHARED_TEMPLATES = ["core.typ"]

# Project guide doc sources are any .typ files in docs/guides/ that are
# not shared templates.
GUIDES_SUBDIR = Path("docs") / "guides"


def find_project_root(start: Path) -> Path | None:
    """
    Walk upward from start to find the project root (contains docs/guides/).

    Args:
        start: Directory to start searching from.

    Returns:
        The project root path, or None if not found.
    """
    current = start.resolve()
    for _ in range(10):
        if (current / GUIDES_SUBDIR).is_dir():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def compile_guides(
    project_dir: Path,
    templates_dir: Path,
    dry_run: bool = False,
) -> int:
    """
    Compile all Typst guide documents in a project to PDF.

    Args:
        project_dir: Project root directory.
        templates_dir: Directory containing shared Typst guide templates.
        dry_run: If True, show what would be done without compiling.

    Returns:
        0 on success, 1 on failure.
    """
    guides_dir = project_dir / GUIDES_SUBDIR

    if not guides_dir.is_dir():
        print(f"ERROR: The guides directory does not exist: {guides_dir}",
              file=sys.stderr)
        return 1

    if not templates_dir.is_dir():
        print(f"ERROR: The templates directory does not exist: {templates_dir}",
              file=sys.stderr)
        return 1

    # Find project .typ sources (exclude shared templates by name).
    shared_names = set(SHARED_TEMPLATES)
    project_sources = sorted(
        p for p in guides_dir.glob("*.typ")
        if p.name not in shared_names
    )

    if not project_sources:
        print("No .typ guide documents were found to compile.")
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
            print(f"  [dry-run] Would compile {src.name} -> {guides_dir / pdf_name}")
        return 0

    # Create temporary build directory, compile, clean up.
    with tempfile.TemporaryDirectory(prefix="typst_guides_build_") as tmp:
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
            pdf_path = guides_dir / pdf_name

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
        description="Compile Typst developer-guide documents to PDF.",
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
            print("ERROR: Could not find a project root with docs/guides/. "
                  "Run from a project directory or use --project-dir.",
                  file=sys.stderr)
            return 1

    if not shutil.which("typst"):
        print("ERROR: The typst compiler was not found in PATH.", file=sys.stderr)
        return 1

    return compile_guides(project_dir, args.templates_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
