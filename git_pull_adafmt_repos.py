#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Michael Gardner, A Bit of Help, Inc.

"""Fetch and pull all repositories used by the adafmt application ecosystem.

This script ensures that local clones of all repositories involved in building,
testing, documenting, and reusing adafmt and its dependencies are up to date
with their GitHub remotes. GitHub is the source of truth.

Before fetching, each repository's origin remote is checked. If it uses HTTPS,
the URL is automatically converted to SSH (git@github.com:owner/repo.git).

If the local branch has diverged from the remote:
  - If there are no uncommitted local changes, the branch is reset to match
    the remote (GitHub is the source of truth).
  - If there are uncommitted local changes, the script warns and exits so the
    user can decide how to handle them.

If any operation fails, the script displays the error and exits immediately.
"""

import os
import re
import subprocess
import sys


# Base directory containing all repositories.
BASE_DIR = os.path.expanduser("~/Ada/github.com/abitofhelp")

# Repositories to update, sorted alphabetically.
REPOS = [
    "abohlib",
    "adafmt",
    "astfmt",
    "clara",
    "corpus_ada",
    "deps26",
    "functional",
    "hybrid_app_ada",
    "hybrid_app_docs",
    "hybrid_lib_ada",
    "hybrid_lib_docs",
    "hybrid_scripts_python",
    "hybrid_test_python",
]

# Pattern matching HTTPS GitHub URLs (with or without user@ prefix).
HTTPS_PATTERN = re.compile(
    r"^https://(?:[^@]+@)?github\.com/(.+)$"
)


def _run(cmd: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
    """Run a command and return the result."""
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def ensure_ssh_remote(repo_path: str, name: str) -> None:
    """Convert the origin remote from HTTPS to SSH if necessary."""
    result = _run(["git", "remote", "get-url", "origin"], repo_path)
    if result.returncode != 0:
        print(f"ERROR: Could not read the origin remote URL for {name}.")
        if result.stderr:
            print(result.stderr.rstrip())
        sys.exit(1)

    url = result.stdout.strip()
    match = HTTPS_PATTERN.match(url)
    if not match:
        return  # Already SSH or another protocol.

    repo_slug = match.group(1)
    ssh_url = f"git@github.com:{repo_slug}"
    print(f"  Converting remote from HTTPS to SSH: {ssh_url}")

    result = _run(["git", "remote", "set-url", "origin", ssh_url], repo_path)
    if result.returncode != 0:
        print(f"ERROR: Failed to set the SSH remote URL for {name}.")
        if result.stderr:
            print(result.stderr.rstrip())
        sys.exit(1)


def ensure_on_main(repo_path: str, name: str) -> None:
    """Switch to the main branch if not already on it."""
    result = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    if result.returncode != 0:
        print(f"ERROR: Could not determine the current branch for {name}.")
        sys.exit(1)

    branch = result.stdout.strip()
    if branch != "main":
        print(f"  Switching from '{branch}' to 'main'.")
        result = _run(["git", "checkout", "main"], repo_path)
        if result.returncode != 0:
            print(f"ERROR: Could not switch to 'main' in {name}.")
            if result.stderr:
                print(result.stderr.rstrip())
            sys.exit(1)


def ensure_tracking(repo_path: str, name: str) -> None:
    """Ensure the main branch tracks origin/main."""
    result = _run(
        ["git", "config", "branch.main.remote"],
        repo_path,
    )
    if result.returncode != 0 or not result.stdout.strip():
        print(f"  Setting upstream tracking to origin/main.")
        result = _run(
            ["git", "branch", "--set-upstream-to=origin/main", "main"],
            repo_path,
        )
        if result.returncode != 0:
            print(f"ERROR: Could not set upstream tracking for {name}.")
            if result.stderr:
                print(result.stderr.rstrip())
            sys.exit(1)


def has_local_changes(repo_path: str) -> bool:
    """Return True if the working tree has uncommitted changes."""
    result = _run(["git", "status", "--porcelain"], repo_path)
    return bool(result.stdout.strip())


def has_diverged(repo_path: str) -> bool:
    """Return True if the local branch and remote have diverged."""
    local = _run(["git", "rev-parse", "main"], repo_path).stdout.strip()
    remote = _run(["git", "rev-parse", "origin/main"], repo_path).stdout.strip()
    base = _run(["git", "merge-base", "main", "origin/main"], repo_path).stdout.strip()

    # Diverged means both sides have commits the other doesn't.
    # Also handle the case where local is simply behind.
    return local != remote and local != base


def resolve_divergence(repo_path: str, name: str) -> None:
    """Reset the local branch to match origin/main if safe to do so."""
    if has_local_changes(repo_path):
        print(
            f"ERROR: {name} has diverged from origin/main AND has uncommitted "
            f"local changes. Please resolve manually."
        )
        sys.exit(1)

    print(f"  Local branch has diverged. Resetting to origin/main (GitHub is truth).")
    result = _run(["git", "reset", "--hard", "origin/main"], repo_path)
    if result.returncode != 0:
        print(f"ERROR: Could not reset {name} to origin/main.")
        if result.stderr:
            print(result.stderr.rstrip())
        sys.exit(1)
    print(f"  {result.stdout.strip()}")


def update_repo(name: str) -> None:
    """Ensure SSH remote, then fetch and pull a single repository."""
    repo_path = os.path.join(BASE_DIR, name)

    if not os.path.isdir(repo_path):
        print(f"ERROR: The repository directory does not exist: {repo_path}")
        sys.exit(1)

    print(f"\n--- {name} ---")

    ensure_ssh_remote(repo_path, name)
    ensure_on_main(repo_path, name)

    # Fetch first so we have current remote refs.
    result = _run(["git", "fetch", "--all"], repo_path)
    if result.returncode != 0:
        print(f"ERROR: 'git fetch --all' failed in {repo_path}")
        if result.stderr:
            print(result.stderr.rstrip())
        sys.exit(1)

    ensure_tracking(repo_path, name)

    # Check for divergence after fetch.
    if has_diverged(repo_path, ):
        resolve_divergence(repo_path, name)
    else:
        # Normal fast-forward pull.
        result = _run(["git", "pull"], repo_path)
        if result.returncode != 0:
            print(f"ERROR: 'git pull' failed in {repo_path}")
            if result.stderr:
                print(result.stderr.rstrip())
            if result.stdout:
                print(result.stdout.rstrip())
            sys.exit(1)
        if result.stdout.strip():
            print(result.stdout.rstrip())


def main() -> None:
    """Update all repositories."""
    print(f"Updating {len(REPOS)} repositories in {BASE_DIR}")

    for repo in REPOS:
        update_repo(repo)

    print(f"\nAll {len(REPOS)} repositories are up to date.")


if __name__ == "__main__":
    main()
