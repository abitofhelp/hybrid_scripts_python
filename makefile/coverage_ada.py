#!/usr/bin/env python3
"""
GNATcoverage Analysis Tool for Ada Projects

Consolidated script that handles:
1. Building the GNATcov runtime library (if needed)
2. Instrumenting test projects for coverage
3. Running instrumented tests
4. Generating HTML and text coverage reports

Usage:
    python3 coverage_ada.py [--rebuild-runtime] [--unit-only] [--integration-only]

Options:
    --rebuild-runtime    Force rebuild of GNATcov runtime
    --unit-only          Only run unit tests
    --integration-only   Only run integration tests

Output:
    coverage/report/index.html  - HTML coverage report
    coverage/summary.txt        - Text summary
"""

import argparse
import os
import shutil
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
        self.test_dir = root / "test"  # Directory with alire.toml containing gnatcov
        self.unit_tests_gpr = root / "test" / "unit" / "unit_tests.gpr"
        self.integration_tests_gpr = root / "test" / "integration" / "integration_tests.gpr"
        self.unit_runner = root / "test" / "bin" / "unit_runner"
        self.integration_runner = root / "test" / "bin" / "integration_runner"
        self.coverage_dir = root / "coverage"
        self.traces_dir = self.coverage_dir / "traces"
        self.report_dir = self.coverage_dir / "report"
        self.gnatcov_rts_prefix = root / "external" / "gnatcov_rts" / "install"


# =============================================================================
# Utilities
# =============================================================================

def find_project_root() -> Path:
    """Find the project root (directory containing alire.toml)."""
    current = Path.cwd()
    for parent in [current] + list(current.parents):
        if (parent / "alire.toml").exists():
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


def run_alr(args: list[str], cwd: Path | None = None, env: dict | None = None,
            check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    """Run a command via 'alr exec --'."""
    return run_cmd(["alr", "exec", "--"] + args, cwd=cwd, env=env, check=check, capture=capture)


# =============================================================================
# Step 1: Build GNATcov Runtime
# =============================================================================

def find_gnatcov_rts_source(root: Path) -> Path | None:
    """Find the gnatcov_rts source in Alire dependencies."""
    search_paths = [
        root / "alire" / "cache" / "dependencies",
        root / "test" / "alire" / "cache" / "dependencies",
    ]
    for search_path in search_paths:
        if not search_path.exists():
            continue
        for dep_dir in search_path.iterdir():
            if dep_dir.name.startswith("gnatcov_"):
                rts_path = dep_dir / "share" / "gnatcoverage" / "gnatcov_rts"
                if rts_path.exists():
                    return rts_path
    return None


def build_gnatcov_runtime(cfg: Config, force: bool = False) -> bool:
    """Build and install the GNATcov runtime library."""
    print("\n" + "=" * 70)
    print("Step 1: GNATcov Runtime")
    print("=" * 70)

    # Check if already built
    if not force and (cfg.gnatcov_rts_prefix / "share" / "gpr").exists():
        print(f"✓ Runtime already installed at {cfg.gnatcov_rts_prefix}")
        return True

    # Find source
    rts_source = find_gnatcov_rts_source(cfg.root)
    if rts_source is None:
        print("✗ Cannot find gnatcov_rts in Alire dependencies.")
        print("  Add to test/alire.toml: gnatcov = \"*\"")
        print("  Then run: cd test && alr update")
        return False

    print(f"  Building from: {rts_source}")
    print(f"  Installing to: {cfg.gnatcov_rts_prefix}")

    # Clean if forcing rebuild
    if force and cfg.gnatcov_rts_prefix.exists():
        shutil.rmtree(cfg.gnatcov_rts_prefix)

    cfg.gnatcov_rts_prefix.mkdir(parents=True, exist_ok=True)

    # Find GPR file
    gpr_file = rts_source / "gnatcov_rts_full.gpr"
    if not gpr_file.exists():
        gpr_file = rts_source / "gnatcov_rts.gpr"
    if not gpr_file.exists():
        print(f"✗ Cannot find gnatcov_rts GPR file in {rts_source}")
        return False

    # Build
    try:
        run_cmd([
            "gprbuild", "-P", str(gpr_file), "-p", "-j0",
            f"--relocate-build-tree={cfg.gnatcov_rts_prefix}/obj",
        ], cwd=rts_source)
    except subprocess.CalledProcessError:
        print("✗ gprbuild failed")
        return False

    # Install
    try:
        run_cmd([
            "gprinstall", "-P", str(gpr_file), "-p",
            f"--prefix={cfg.gnatcov_rts_prefix}",
            f"--relocate-build-tree={cfg.gnatcov_rts_prefix}/obj",
            "--mode=usage",
        ], cwd=rts_source)
    except subprocess.CalledProcessError:
        print("✗ gprinstall failed")
        return False

    print("✓ GNATcov runtime installed")
    return True


# =============================================================================
# Step 2: Instrument Tests
# =============================================================================

def instrument_tests(cfg: Config, run_unit: bool, run_integration: bool) -> bool:
    """Instrument test projects for coverage."""
    print("\n" + "=" * 70)
    print("Step 2: Instrument Tests")
    print("=" * 70)

    # Clean previous instrumentation
    for instr_dir in cfg.root.glob("**/gnatcov-instr"):
        shutil.rmtree(instr_dir, ignore_errors=True)

    env = {"GPR_PROJECT_PATH": f"{cfg.gnatcov_rts_prefix}:{os.environ.get('GPR_PROJECT_PATH', '')}"}

    if run_unit and cfg.unit_tests_gpr.exists():
        print("\n  Instrumenting unit tests...")
        try:
            run_alr([
                "gnatcov", "instrument",
                "-P", str(cfg.unit_tests_gpr),
                "--level=stmt+decision",
                "--dump-trigger=atexit",
                "--dump-channel=bin-file",
            ], cwd=cfg.test_dir, env=env)
        except subprocess.CalledProcessError:
            print("✗ Unit test instrumentation failed")
            return False

    if run_integration and cfg.integration_tests_gpr.exists():
        print("\n  Instrumenting integration tests...")
        try:
            run_alr([
                "gnatcov", "instrument",
                "-P", str(cfg.integration_tests_gpr),
                "--level=stmt+decision",
                "--dump-trigger=atexit",
                "--dump-channel=bin-file",
            ], cwd=cfg.test_dir, env=env)
        except subprocess.CalledProcessError:
            print("✗ Integration test instrumentation failed")
            return False

    print("✓ Instrumentation complete")
    return True


# =============================================================================
# Step 3: Build Instrumented Tests
# =============================================================================

def build_instrumented_tests(cfg: Config, run_unit: bool, run_integration: bool) -> bool:
    """Build the instrumented test executables."""
    print("\n" + "=" * 70)
    print("Step 3: Build Instrumented Tests")
    print("=" * 70)

    env = {"GPR_PROJECT_PATH": f"{cfg.gnatcov_rts_prefix}:{os.environ.get('GPR_PROJECT_PATH', '')}"}

    if run_unit and cfg.unit_tests_gpr.exists():
        print("\n  Building unit tests...")
        try:
            run_alr([
                "gprbuild", "-f", "-p",
                "-P", str(cfg.unit_tests_gpr),
                "--src-subdirs=gnatcov-instr",
                "--implicit-with=gnatcov_rts_full.gpr",
            ], cwd=cfg.test_dir, env=env)
        except subprocess.CalledProcessError:
            print("✗ Unit test build failed")
            return False

    if run_integration and cfg.integration_tests_gpr.exists():
        print("\n  Building integration tests...")
        try:
            run_alr([
                "gprbuild", "-f", "-p",
                "-P", str(cfg.integration_tests_gpr),
                "--src-subdirs=gnatcov-instr",
                "--implicit-with=gnatcov_rts_full.gpr",
            ], cwd=cfg.test_dir, env=env)
        except subprocess.CalledProcessError:
            print("✗ Integration test build failed")
            return False

    print("✓ Build complete")
    return True


# =============================================================================
# Step 4: Run Tests
# =============================================================================

def run_tests(cfg: Config, run_unit: bool, run_integration: bool) -> bool:
    """Run the instrumented tests to generate trace files."""
    print("\n" + "=" * 70)
    print("Step 4: Run Tests")
    print("=" * 70)

    # Setup trace output directory
    cfg.traces_dir.mkdir(parents=True, exist_ok=True)
    env = {"GNATCOV_TRACE_FILE": str(cfg.traces_dir) + "/"}

    success = True

    if run_unit and cfg.unit_runner.exists():
        print("\n  Running unit tests...")
        result = run_cmd([str(cfg.unit_runner)], env=env, check=False)
        if result.returncode != 0:
            print("  ⚠ Unit tests had failures (continuing for coverage)")

    if run_integration and cfg.integration_runner.exists():
        print("\n  Running integration tests...")
        result = run_cmd([str(cfg.integration_runner)], env=env, check=False)
        if result.returncode != 0:
            print("  ⚠ Integration tests had failures (continuing for coverage)")

    # Check for trace files
    traces = list(cfg.traces_dir.glob("*.srctrace"))
    if not traces:
        print("✗ No trace files generated")
        return False

    print(f"✓ Generated {len(traces)} trace file(s)")
    return True


# =============================================================================
# Step 5: Generate Reports
# =============================================================================

def generate_reports(cfg: Config) -> bool:
    """Generate coverage reports from trace files."""
    print("\n" + "=" * 70)
    print("Step 5: Generate Coverage Reports")
    print("=" * 70)

    cfg.report_dir.mkdir(parents=True, exist_ok=True)

    # Collect SID files
    sid_list = cfg.coverage_dir / "sid.list"
    sid_files = list(cfg.root.glob("obj/**/*.sid"))
    if not sid_files:
        print("✗ No SID files found")
        return False

    with open(sid_list, "w") as f:
        for sid in sid_files:
            f.write(f"{sid}\n")
    print(f"  Found {len(sid_files)} SID file(s)")

    # Collect trace files
    trace_list = cfg.coverage_dir / "traces.list"
    trace_files = list(cfg.traces_dir.glob("*.srctrace"))
    with open(trace_list, "w") as f:
        for trace in trace_files:
            f.write(f"{trace}\n")
    print(f"  Found {len(trace_files)} trace file(s)")

    # Generate HTML report
    print("\n  Generating HTML report...")
    try:
        run_alr([
            "gnatcov", "coverage",
            "--level=stmt+decision",
            "--sid", f"@{sid_list}",
            "--annotate=html",
            "--output-dir", str(cfg.report_dir),
            f"@{trace_list}",
        ], cwd=cfg.test_dir)
    except subprocess.CalledProcessError:
        print("✗ HTML report generation failed")
        return False

    # Generate text summary
    summary_file = cfg.coverage_dir / "summary.txt"
    print("\n  Generating text summary...")
    try:
        result = run_alr([
            "gnatcov", "coverage",
            "--level=stmt+decision",
            "--sid", f"@{sid_list}",
            "--annotate=report",
            f"@{trace_list}",
        ], cwd=cfg.test_dir, capture=True, check=False)
        with open(summary_file, "w") as f:
            f.write(result.stdout)
    except subprocess.CalledProcessError:
        print("  ⚠ Text summary generation failed")

    print("\n" + "=" * 70)
    print("✓ Coverage Analysis Complete!")
    print("=" * 70)
    print(f"\n  HTML Report: {cfg.report_dir / 'index.html'}")
    print(f"  Summary:     {summary_file}")

    # Print summary excerpt
    if summary_file.exists():
        print("\n" + "-" * 70)
        print("Coverage Summary:")
        print("-" * 70)
        with open(summary_file) as f:
            for i, line in enumerate(f):
                if i < 40:
                    print(line.rstrip())

    return True


# =============================================================================
# Main
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="GNATcoverage analysis for Ada projects"
    )
    parser.add_argument(
        "--rebuild-runtime", action="store_true",
        help="Force rebuild of GNATcov runtime"
    )
    parser.add_argument(
        "--unit-only", action="store_true",
        help="Only run unit tests"
    )
    parser.add_argument(
        "--integration-only", action="store_true",
        help="Only run integration tests"
    )
    args = parser.parse_args()

    # Determine which tests to run
    run_unit = not args.integration_only
    run_integration = not args.unit_only

    # Find project and configure
    root = find_project_root()
    cfg = Config(root)

    print("=" * 70)
    print("GNATcoverage Analysis")
    print("=" * 70)
    print(f"Project root: {root}")

    # Clean previous coverage data
    if cfg.traces_dir.exists():
        shutil.rmtree(cfg.traces_dir)
    cfg.coverage_dir.mkdir(parents=True, exist_ok=True)

    # Execute steps
    if not build_gnatcov_runtime(cfg, force=args.rebuild_runtime):
        return 1

    if not instrument_tests(cfg, run_unit, run_integration):
        return 1

    if not build_instrumented_tests(cfg, run_unit, run_integration):
        return 1

    if not run_tests(cfg, run_unit, run_integration):
        return 1

    if not generate_reports(cfg):
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
