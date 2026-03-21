#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Michael Gardner, A Bit of Help, Inc.

"""Run an Alire build command, filter output to diagnostics, propagate exit code.

This script wraps any Alire or GPRbuild command, captures its output, and
displays only lines matching diagnostic patterns (warnings, errors, style
messages, and build status). The original command's exit code is preserved
and propagated, ensuring that build failures are never silently swallowed.

Usage from Makefile:
    ALR_BUILD = python3 scripts/python/shared/makefile/alr_build.py $(ALR)

    build:
        @$(ALR_BUILD) build --development -- $(ALR_BUILD_FLAGS)
"""

import re
import subprocess
import sys

# Patterns to display from build output.
DIAGNOSTIC_PATTERN = re.compile(
    r"warning:|error:|\(style\)|finished|Success|FAILED|failed"
)


def main() -> int:
    """Run the command, filter output, and return its exit code."""
    if len(sys.argv) < 2:
        print("Usage: alr_build.py <command> [args...]", file=sys.stderr)
        return 1

    result = subprocess.run(
        sys.argv[1:],
        capture_output=True,
        text=True,
    )

    output = (result.stdout + result.stderr).splitlines()
    filtered = [line for line in output if DIAGNOSTIC_PATTERN.search(line)]

    if result.returncode != 0 and not filtered:
        # Build failed but no diagnostics matched — show full output
        # so the failure is never silent.
        for line in output:
            print(line)
    else:
        for line in filtered:
            print(line)

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
