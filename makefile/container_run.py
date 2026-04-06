#!/usr/bin/env python3
# ==============================================================================
# container_run.py
# ==============================================================================
# Copyright (c) 2025 Michael Gardner, A Bit of Help, Inc.
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE file in the project root.
#
# Purpose:
#   Launch a dev container with automatic CLI detection and predictable
#   naming.  Detects the host platform, selects the appropriate container
#   CLI (docker, nerdctl, or podman), generates a sequential container
#   name, and passes host identity for runtime user adaptation.
#
# Usage:
#   Direct invocation:
#     python3 container_run.py --image dev-container-ada-system
#     python3 container_run.py --image dev-container-go --source ~/Go/src
#     python3 container_run.py --image dev-container-ada --cli docker --dry-run
#
#   From a Makefile:
#     CONTAINER_RUN = python3 path/to/container_run.py
#
#     run:
#         @$(CONTAINER_RUN) --image $(IMAGE_NAME) --source "$(CURDIR)"
#
# Design Notes:
#   Platform CLI defaults: macOS -> docker, Linux -> nerdctl,
#   Windows -> docker.  Override with --cli.
#
#   Container names follow the pattern image-N where N increments from
#   the highest existing container with that prefix (e.g.,
#   dev-container-ada-1, dev-container-ada-2).
#
#   Host identity (UID, GID, username) is passed via environment
#   variables for runtime user adaptation by entrypoint.sh.  On
#   Windows (native), UID/GID are unavailable and the container
#   falls back to its default user (dev:1000:1000).
#
#   Podman rootless uses --userns=keep-id instead of HOST_*
#   environment variables.
#
# See Also:
#   common.py     - shared utilities (OS detection, command helpers)
#   entrypoint.sh - container-side user adaptation logic
# ==============================================================================

import argparse
import getpass
import os
import platform
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Import shared utilities from the parent package.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR.parent))

from common import (  # noqa: E402
    command_exists,
    is_linux,
    is_macos,
    is_windows,
    print_error,
    print_info,
    print_success,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_REGISTRY = "ghcr.io/abitofhelp"
DEFAULT_TAG = "latest"
DEFAULT_WORKDIR = "/workspace"


# ==============================================================================
# CLI Detection
# ==============================================================================

def detect_container_cli(override: Optional[str] = None) -> str:
    """Select the container CLI for the current platform.

    Resolution order:
      1. Explicit *override* (--cli flag).
      2. Platform default: macOS/Windows -> docker, Linux -> nerdctl.
      3. Fallback: if the default is missing, try the alternative.

    Args:
        override: CLI name supplied by the caller, or ``None``.

    Returns:
        The name of an available container CLI.
    """
    if override:
        if not command_exists(override):
            print_error(
                f"The specified container CLI is not installed: {override}"
            )
            sys.exit(1)
        return override

    if is_macos() or is_windows():
        preferred, fallback = "docker", "nerdctl"
    else:
        preferred, fallback = "nerdctl", "docker"

    if command_exists(preferred):
        return preferred

    if command_exists(fallback):
        print_info(f"{preferred} was not found; using {fallback} instead.")
        return fallback

    print_error("No container CLI was found.  Install docker or nerdctl.")
    sys.exit(1)


# ==============================================================================
# Container Naming
# ==============================================================================

def next_container_name(cli: str, image: str) -> str:
    """Return the next sequential container name for *image*.

    Queries the CLI for all containers (running and stopped) whose name
    matches ``<image>-<N>``, finds the highest *N*, and returns
    ``<image>-<N+1>``.  If no matching containers exist or the query
    fails, the name defaults to ``<image>-1``.
    """
    try:
        result = subprocess.run(
            [cli, "ps", "-a", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return f"{image}-1"

    if result.returncode != 0:
        return f"{image}-1"

    prefix = f"{image}-"
    max_num = 0
    for line in result.stdout.splitlines():
        name = line.strip()
        if name.startswith(prefix):
            suffix = name[len(prefix):]
            if suffix.isdigit():
                num = int(suffix)
                if num > max_num:
                    max_num = num

    return f"{image}-{max_num + 1}"


# ==============================================================================
# Host Identity
# ==============================================================================

def get_host_identity() -> dict[str, str]:
    """Collect host user identity for the container entrypoint.

    On POSIX systems, returns HOST_USER, HOST_UID, and HOST_GID.
    On Windows (native), UID and GID are unavailable; only HOST_USER
    is returned and the container entrypoint falls back to its default
    user (dev:1000:1000).
    """
    identity: dict[str, str] = {"HOST_USER": getpass.getuser()}

    # os.getuid() / os.getgid() exist on POSIX but not on Windows.
    if hasattr(os, "getuid"):
        identity["HOST_UID"] = str(os.getuid())
    if hasattr(os, "getgid"):
        identity["HOST_GID"] = str(os.getgid())

    return identity


# ==============================================================================
# Command Builder
# ==============================================================================

def build_run_command(
    *,
    cli: str,
    image_ref: str,
    container_name: str,
    source_dir: str,
    workdir: str,
    host_identity: dict[str, str],
    root: bool = False,
) -> list[str]:
    """Assemble the ``<cli> run`` argument list.

    Args:
        cli:             Container CLI name (docker, nerdctl, podman).
        image_ref:       Fully qualified image reference.
        container_name:  Name to assign to the container.
        source_dir:      Host directory to bind-mount.
        workdir:         Mount point inside the container.
        host_identity:   HOST_USER / HOST_UID / HOST_GID mapping.
        root:            If True, bypass the entrypoint and run as UID 0.
    """
    interactive = ["-it"] if sys.stdin.isatty() else []

    cmd: list[str] = [cli, "run", *interactive, "--rm",
                       "--name", container_name]

    if root:
        # Diagnostic mode: bypass entrypoint, run as root.
        cmd.extend(["--entrypoint", "/usr/bin/zsh", "-u", "0"])
    elif cli == "podman":
        # Podman rootless maps the host user directly; no HOST_* needed.
        cmd.append("--userns=keep-id")
    else:
        # Docker / nerdctl: pass host identity for entrypoint adaptation.
        for key, value in host_identity.items():
            cmd.extend(["-e", f"{key}={value}"])

    cmd.extend([
        "-v", f"{source_dir}:{workdir}",
        "-w", workdir,
        image_ref,
    ])

    return cmd


# ==============================================================================
# Argument Parsing
# ==============================================================================

def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Launch a dev container with automatic CLI detection "
            "and predictable naming."
        ),
    )
    parser.add_argument(
        "--image",
        required=True,
        help="Container image name (e.g., dev-container-ada-system).",
    )
    parser.add_argument(
        "--source",
        default=None,
        help=(
            "Host source directory to bind-mount into the container.  "
            "Defaults to the current working directory."
        ),
    )
    parser.add_argument(
        "--registry",
        default=DEFAULT_REGISTRY,
        help=f"Container registry prefix (default: {DEFAULT_REGISTRY}).",
    )
    parser.add_argument(
        "--tag",
        default=DEFAULT_TAG,
        help=f"Image tag (default: {DEFAULT_TAG}).",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help=(
            "Use the local image name instead of the full registry "
            "reference.  Useful for testing locally-built images."
        ),
    )
    parser.add_argument(
        "--cli",
        default=None,
        metavar="CLI",
        help="Override container CLI detection (docker, nerdctl, podman).",
    )
    parser.add_argument(
        "--workdir",
        default=DEFAULT_WORKDIR,
        help=f"Container working directory (default: {DEFAULT_WORKDIR}).",
    )
    parser.add_argument(
        "--root",
        action="store_true",
        help="Run as root, bypassing the entrypoint (diagnostic).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the command without executing it.",
    )

    return parser.parse_args(argv)


# ==============================================================================
# Entry Point
# ==============================================================================

def main(argv: Optional[list[str]] = None) -> int:
    """Launch a dev container."""
    args = parse_args(argv)

    # -- Resolve and validate source directory ---------------------------
    source = Path(args.source or os.getcwd()).resolve()
    if not source.is_dir():
        print_error(f"The source directory does not exist: {source}")
        return 1

    # -- Detect container CLI --------------------------------------------
    cli = detect_container_cli(args.cli)

    # -- Build image reference -------------------------------------------
    if args.local:
        image_ref = args.image
    else:
        image_ref = f"{args.registry}/{args.image}:{args.tag}"

    # -- Generate container name -----------------------------------------
    container_name = next_container_name(cli, args.image)

    # -- Collect host identity -------------------------------------------
    host_identity = get_host_identity()

    # -- Assemble command ------------------------------------------------
    cmd = build_run_command(
        cli=cli,
        image_ref=image_ref,
        container_name=container_name,
        source_dir=str(source),
        workdir=args.workdir,
        host_identity=host_identity,
        root=args.root,
    )

    # -- Execute or dry-run ----------------------------------------------
    arch = platform.machine()
    print_info(f"Launching {args.image} on {arch} as {container_name}...")

    if args.dry_run:
        print(shlex.join(cmd))
        return 0

    try:
        result = subprocess.run(cmd)
        if result.returncode == 0:
            print_success(f"Container {container_name} exited cleanly.")
        return result.returncode
    except KeyboardInterrupt:
        print()
        return 130
    except FileNotFoundError:
        print_error(f"The container CLI was not found: {cli}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
