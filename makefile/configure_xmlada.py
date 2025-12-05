#!/usr/bin/env python3
# ==============================================================================
# configure_xmlada.py - Configure xmlada dependency in Alire cache
# ==============================================================================
# Copyright (c) 2025 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE file in the project root.
#
# Purpose:
#   When Alire pulls xmlada as a transitive dependency (via gnatcoll/libgpr),
#   it doesn't run configure, leaving xmlada_shared.gpr missing. This script
#   finds xmlada directories in the test crate's Alire cache and runs configure.
#
# Usage:
#   python3 scripts/python/makefile/configure_xmlada.py
#   python3 scripts/python/makefile/configure_xmlada.py --verbose
#   python3 scripts/python/makefile/configure_xmlada.py --project-root /path/to/project
#
# ==============================================================================

import argparse
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from common import configure_xmlada_dependency, print_success, print_error, print_info


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Configure xmlada dependency in Alire cache',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This script fixes the "xmlada_shared.gpr not found" error that occurs when
Alire pulls xmlada as a transitive dependency. It finds xmlada directories
in test/alire/cache/dependencies/ and runs ./configure in each.

Examples:
  %(prog)s                     # Configure xmlada in current project
  %(prog)s --verbose           # Show detailed progress
  %(prog)s --project-root ..   # Specify project root directory
        """
    )

    parser.add_argument(
        '--project-root',
        type=Path,
        default=Path.cwd(),
        help='Project root directory (default: current directory)'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed progress'
    )

    args = parser.parse_args()

    project_root = args.project_root.resolve()
    if not project_root.exists():
        print_error(f"Project root does not exist: {project_root}")
        return 1

    if args.verbose:
        print_info(f"Project root: {project_root}")

    success = configure_xmlada_dependency(project_root, verbose=args.verbose)

    if success:
        print_success("xmlada configuration complete")
        return 0
    else:
        print_error("Some xmlada directories could not be configured")
        return 1


if __name__ == '__main__':
    sys.exit(main())
