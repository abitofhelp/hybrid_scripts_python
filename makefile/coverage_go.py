#!/usr/bin/env python3
"""
Go Coverage Analysis Tool

Consolidated script that handles:
1. Running tests with coverage profiling
2. Generating HTML and text coverage reports

Usage:
    python3 coverage_go.py [--verbose] [--packages PATTERN]

Options:
    --verbose           Show detailed test output
    --packages PATTERN  Package pattern to test (default: ./...)

Output:
    coverage/report/index.html  - HTML coverage report
    coverage/summary.txt        - Text summary
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


# =============================================================================
# Configuration
# =============================================================================

class Config:
    """Project configuration - adjust these for your project structure."""

    def __init__(self, root: Path):
        self.root = root
        self.coverage_dir = root / "coverage"
        self.report_dir = self.coverage_dir / "report"
        self.profile_file = self.coverage_dir / "coverage.out"
        self.summary_file = self.coverage_dir / "summary.txt"


# =============================================================================
# Utilities
# =============================================================================

def find_project_root() -> Path:
    """Find the project root (directory containing go.mod)."""
    current = Path.cwd()
    for parent in [current] + list(current.parents):
        if (parent / "go.mod").exists():
            return parent
    # Fallback: use git root
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return Path(result.stdout.strip())
    except subprocess.CalledProcessError:
        return current


def run_cmd(cmd: list[str], cwd: Path | None = None, env: dict | None = None,
            check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    """Run a command with nice output."""
    print(f"  → {' '.join(str(c) for c in cmd)}")
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(
        cmd, cwd=cwd, env=merged_env, check=check,
        capture_output=capture, text=True,
    )


# =============================================================================
# Step 1: Run Tests with Coverage
# =============================================================================

def run_tests_with_coverage(cfg: Config, packages: str, verbose: bool) -> bool:
    """Run Go tests with coverage profiling."""
    print("\n" + "=" * 70)
    print("Step 1: Run Tests with Coverage")
    print("=" * 70)

    # Ensure coverage directory exists
    cfg.coverage_dir.mkdir(parents=True, exist_ok=True)

    # Build test command
    cmd = [
        "go", "test",
        f"-coverprofile={cfg.profile_file}",
        "-covermode=atomic",
    ]

    if verbose:
        cmd.append("-v")

    cmd.append(packages)

    print(f"\n  Testing packages: {packages}")
    try:
        run_cmd(cmd, cwd=cfg.root)
    except subprocess.CalledProcessError:
        print("  ⚠ Some tests failed (continuing for coverage)")

    # Check if coverage file was generated
    if not cfg.profile_file.exists():
        print("✗ No coverage profile generated")
        return False

    print("✓ Tests completed with coverage")
    return True


# =============================================================================
# Step 2: Generate Reports
# =============================================================================

def generate_reports(cfg: Config) -> bool:
    """Generate coverage reports from profile."""
    print("\n" + "=" * 70)
    print("Step 2: Generate Coverage Reports")
    print("=" * 70)

    cfg.report_dir.mkdir(parents=True, exist_ok=True)

    # Generate HTML report
    html_file = cfg.report_dir / "index.html"
    print("\n  Generating HTML report...")
    try:
        run_cmd([
            "go", "tool", "cover",
            f"-html={cfg.profile_file}",
            f"-o={html_file}",
        ], cwd=cfg.root)
    except subprocess.CalledProcessError:
        print("✗ HTML report generation failed")
        return False

    # Generate text summary (function-level coverage)
    print("\n  Generating text summary...")
    try:
        result = run_cmd([
            "go", "tool", "cover",
            f"-func={cfg.profile_file}",
        ], cwd=cfg.root, capture=True)

        with open(cfg.summary_file, "w") as f:
            f.write("** GO COVERAGE REPORT **\n\n")
            f.write("=" * 70 + "\n")
            f.write("Function Coverage Summary\n")
            f.write("=" * 70 + "\n\n")
            f.write(result.stdout)

    except subprocess.CalledProcessError:
        print("  ⚠ Text summary generation failed")

    # Calculate and display overall coverage
    print("\n" + "=" * 70)
    print("✓ Coverage Analysis Complete!")
    print("=" * 70)
    print(f"\n  HTML Report: {html_file}")
    print(f"  Summary:     {cfg.summary_file}")
    print(f"  Profile:     {cfg.profile_file}")

    # Print summary excerpt
    if cfg.summary_file.exists():
        print("\n" + "-" * 70)
        print("Coverage Summary:")
        print("-" * 70)
        with open(cfg.summary_file) as f:
            lines = f.readlines()
            # Show last 20 lines (includes totals)
            for line in lines[-25:]:
                print(line.rstrip())

    return True


# =============================================================================
# Main
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Go coverage analysis"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show detailed test output"
    )
    parser.add_argument(
        "--packages", default="./...",
        help="Package pattern to test (default: ./...)"
    )
    args = parser.parse_args()

    # Find project and configure
    root = find_project_root()
    cfg = Config(root)

    print("=" * 70)
    print("Go Coverage Analysis")
    print("=" * 70)
    print(f"Project root: {root}")

    # Execute steps
    if not run_tests_with_coverage(cfg, args.packages, args.verbose):
        return 1

    if not generate_reports(cfg):
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
