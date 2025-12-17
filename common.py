#!/usr/bin/env python3
# ==============================================================================
# common.py
# ==============================================================================
# Copyright (c) 2025 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE file in the project root.
#
# Purpose:
#   Shared utilities for project automation scripts.
#       Provides OS detection, terminal colors, command execution helpers,
#       and common operations used across all scripts.
#
# Usage:
#   Import utilities in other scripts:
#          from common import print_success, command_exists, is_macos
#
#          if command_exists('gcovr'):
#              print_success("gcovr is installed")
#
# Design Notes:
#   Design as pure utility module - no side effects
#       All functions are stateless and reusable
#       Terminal colors use ANSI escape codes for cross-platform support
#
# See Also:
#   install_tools.py - uses OS detection and command execution
#       run_coverage.py - uses command execution and print functions
#       Python os and shutil modules for platform operations
# ==============================================================================

import platform
import re
import shutil
import subprocess
import sys
from enum import Enum
from pathlib import Path
from typing import Optional


# ANSI color codes for terminal output
class Colors:
    """Terminal color codes for formatted output."""
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    ORANGE = '\033[0;33m'
    BOLD = '\033[1m'
    NC = '\033[0m'  # No Color


def print_success(message: str) -> None:
    """Print a success message in green."""
    print(f"{Colors.GREEN}✓ {message}{Colors.NC}")


def print_error(message: str) -> None:
    """Print an error message in red."""
    print(f"{Colors.RED}✗ {message}{Colors.NC}", file=sys.stderr)


def print_warning(message: str) -> None:
    """Print a warning message in yellow."""
    print(f"{Colors.YELLOW}⚠ {message}{Colors.NC}")


def print_info(message: str) -> None:
    """Print an info message in cyan."""
    print(f"{Colors.CYAN}{message}{Colors.NC}")


def print_section(message: str) -> None:
    """Print a section header in blue."""
    print(f"{Colors.BLUE}{message}{Colors.NC}")


def command_exists(command: str) -> bool:
    """Check if a command exists in PATH."""
    return shutil.which(command) is not None


def run_command(cmd: list[str], check: bool = True, capture: bool = False) -> Optional[subprocess.CompletedProcess]:
    """
    Run a shell command.

    Args:
        cmd: Command as list of strings
        check: Raise exception on non-zero exit
        capture: Capture stdout/stderr

    Returns:
        CompletedProcess if capture=True, None otherwise
    """
    try:
        if capture:
            return subprocess.run(cmd, check=check, capture_output=True, text=True)
        else:
            subprocess.run(cmd, check=check)
            return None
    except subprocess.CalledProcessError as e:
        if check:
            print_error(f"Command failed: {' '.join(cmd)}")
            raise
        return None


def get_os_type() -> str:
    """
    Get the operating system type.

    Returns:
        'Darwin' for macOS, 'Linux' for Linux, 'Windows' for Windows
    """
    return platform.system()


def is_macos() -> bool:
    """Check if running on macOS."""
    return get_os_type() == 'Darwin'


def is_linux() -> bool:
    """Check if running on Linux."""
    return get_os_type() == 'Linux'


def is_windows() -> bool:
    """Check if running on Windows."""
    return get_os_type() == 'Windows'


def detect_package_manager() -> Optional[str]:
    """
    Detect the system package manager on Linux.

    Returns:
        'apt', 'yum', 'dnf', etc., or None if not detected
    """
    if not is_linux():
        return None

    managers = ['apt-get', 'yum', 'dnf', 'pacman', 'zypper']
    for manager in managers:
        if command_exists(manager):
            return manager

    return None


def configure_xmlada_dependency(project_root, verbose: bool = False) -> bool:
    """
    Configure xmlada dependency in Alire cache.

    When Alire pulls xmlada as a transitive dependency (via gnatcoll/libgpr),
    it doesn't run configure, leaving xmlada_shared.gpr missing. This function
    finds xmlada directories in the test crate's Alire cache and runs configure.

    Args:
        project_root: Path to the project root (containing test/alire/cache)
        verbose: Print detailed progress

    Returns:
        True if xmlada was configured (or already configured), False on error
    """
    from pathlib import Path

    if isinstance(project_root, str):
        project_root = Path(project_root)

    cache_dir = project_root / "test" / "alire" / "cache" / "dependencies"
    if not cache_dir.exists():
        if verbose:
            print_info(f"No Alire cache at {cache_dir}")
        return True  # Not an error - cache may not exist yet

    # Find xmlada directories
    xmlada_dirs = list(cache_dir.glob("xmlada_*"))
    if not xmlada_dirs:
        if verbose:
            print_info("No xmlada dependency found in cache")
        return True  # Not an error - project may not need xmlada

    configured_count = 0
    for xmlada_dir in xmlada_dirs:
        shared_gpr = xmlada_dir / "xmlada_shared.gpr"
        configure_script = xmlada_dir / "configure"

        if shared_gpr.exists():
            if verbose:
                print_info(f"xmlada already configured: {xmlada_dir.name}")
            configured_count += 1
            continue

        if not configure_script.exists():
            print_warning(f"No configure script in {xmlada_dir.name}")
            continue

        # Run configure
        if verbose:
            print_info(f"Configuring {xmlada_dir.name}...")

        try:
            result = subprocess.run(
                ["./configure"],
                cwd=str(xmlada_dir),
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode == 0:
                if shared_gpr.exists():
                    print_success(f"Configured xmlada: {xmlada_dir.name}")
                    configured_count += 1
                else:
                    print_warning(f"Configure ran but xmlada_shared.gpr not created")
            else:
                print_warning(f"Configure failed: {result.stderr.strip()}")
        except subprocess.TimeoutExpired:
            print_warning(f"Configure timed out for {xmlada_dir.name}")
        except Exception as e:
            print_warning(f"Error configuring xmlada: {e}")

    return configured_count == len(xmlada_dirs)


# ==============================================================================
# Language Enum and Detection
# ==============================================================================

class Language(Enum):
    """Supported programming languages."""
    GO = 'go'
    ADA = 'ada'
    RUST = 'rust'


def detect_language(project_root: Path) -> Optional[Language]:
    """
    Auto-detect project language based on configuration files.

    Args:
        project_root: Path to project root directory

    Returns:
        Detected Language enum or None if unknown
    """
    if isinstance(project_root, str):
        project_root = Path(project_root)

    # Check for Go
    if (project_root / 'go.mod').exists() or (project_root / 'go.work').exists():
        return Language.GO

    # Check for Ada (GPR files or alire.toml)
    if (project_root / 'alire.toml').exists():
        return Language.ADA
    if list(project_root.glob('*.gpr')):
        return Language.ADA
    if (project_root / 'src').exists() and list((project_root / 'src').glob('**/*.gpr')):
        return Language.ADA

    # Check for Rust
    if (project_root / 'Cargo.toml').exists():
        return Language.RUST

    return None


def detect_project_type(project_root: Path) -> bool:
    """
    Detect if project is a library (vs application).

    Args:
        project_root: Path to project root

    Returns:
        True if library, False if application
    """
    if isinstance(project_root, str):
        project_root = Path(project_root)

    # Check for library/application indicators
    # Go structure: api/, bootstrap/, cmd/ at root
    # Ada structure: src/api/, src/bootstrap/, src/cmd/ under src/
    api_dir = project_root / "api"
    api_dir_ada = project_root / "src" / "api"
    bootstrap_dir = project_root / "bootstrap"
    bootstrap_dir_ada = project_root / "src" / "bootstrap"
    cmd_dir = project_root / "cmd"
    cmd_dir_ada = project_root / "src" / "cmd"

    has_api = api_dir.exists() or api_dir_ada.exists()
    has_bootstrap = bootstrap_dir.exists() or bootstrap_dir_ada.exists()
    has_cmd = cmd_dir.exists() or cmd_dir_ada.exists()

    # Libraries have api/ but not bootstrap/ or cmd/
    if has_api and not has_bootstrap and not has_cmd:
        return True

    # Applications have bootstrap/ and/or cmd/
    if has_bootstrap or has_cmd:
        return False

    # Check GPR files for Library_Name or Library_Kind (Ada projects)
    for gpr_file in project_root.glob("*.gpr"):
        try:
            content = gpr_file.read_text()
            # Library_Name or Library_Kind in GPR indicates a library
            if "Library_Name" in content or "Library_Kind" in content:
                return True
        except Exception:
            pass

    # Check project name as fallback
    project_name = project_root.name.lower()
    if "_lib_" in project_name or project_name.endswith("_lib"):
        return True
    if "_app_" in project_name or project_name.endswith("_app"):
        return False

    # Default to application
    return False


# ==============================================================================
# Case Conversion Utilities
# ==============================================================================

def to_pascal_case(snake_case: str) -> str:
    """
    Convert snake_case to PascalCase.

    Args:
        snake_case: e.g., "my_awesome_app"

    Returns:
        PascalCase: e.g., "MyAwesomeApp"
    """
    return ''.join(word.capitalize() for word in snake_case.split('_'))


def to_ada_pascal_case(snake_case: str) -> str:
    """
    Convert snake_case to Ada PascalCase (preserves underscores).

    Args:
        snake_case: e.g., "my_awesome_app"

    Returns:
        Ada PascalCase: e.g., "My_Awesome_App"
    """
    return '_'.join(word.capitalize() for word in snake_case.split('_'))


def to_snake_case(name: str) -> str:
    """
    Convert various formats to snake_case.

    Args:
        name: e.g., "MyAwesomeApp" or "My_Awesome_App" or "my-awesome-app"

    Returns:
        snake_case: e.g., "my_awesome_app"
    """
    # Replace hyphens with underscores
    name = name.replace('-', '_')

    # Handle Ada Pascal_Case (already has underscores)
    if '_' in name:
        return name.lower()

    # Handle PascalCase - insert underscore before uppercase letters
    result = re.sub(r'([A-Z])', r'_\1', name)
    return result.strip('_').lower()


# ==============================================================================
# Architecture Layer Constants
# ==============================================================================

# 4-layer architecture (libraries)
LIBRARY_LAYERS = ['domain', 'application', 'infrastructure', 'api']

# 5-layer architecture (applications)
APP_LAYERS = ['domain', 'application', 'infrastructure', 'presentation', 'bootstrap']
