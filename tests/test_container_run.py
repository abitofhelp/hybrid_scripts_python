# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
"""Unit tests for ``makefile/container_run.py`` host identity handling.

The dev_containers images (v2.0.0 and later) require HOST_USER, HOST_UID,
and HOST_GID at launch and have no fallback account, so the launcher must
always pass all three, for every container CLI, and must refuse to launch
when they cannot be determined.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "makefile" / "container_run.py"
_SPEC = importlib.util.spec_from_file_location("container_run", _PATH)
container_run = importlib.util.module_from_spec(_SPEC)
sys.modules["container_run"] = container_run
_SPEC.loader.exec_module(container_run)

IDENTITY = {"HOST_USER": "tester", "HOST_UID": "501", "HOST_GID": "20"}


def _env_pairs(cmd: list[str]) -> dict[str, str]:
    pairs = {}
    for i, arg in enumerate(cmd):
        if arg == "-e":
            key, _, value = cmd[i + 1].partition("=")
            pairs[key] = value
    return pairs


def _build(cli: str) -> list[str]:
    return container_run.build_run_command(
        cli=cli,
        image_ref="ghcr.io/abitofhelp/dev-container-ada:latest",
        container_name="dev-container-ada-1",
        source_dir="/src",
        workdir="/workspace",
        host_identity=IDENTITY,
    )


@pytest.mark.parametrize("cli", ["docker", "nerdctl", "podman"])
def test_every_cli_passes_the_full_identity(cli):
    assert _env_pairs(_build(cli)) == IDENTITY


def test_podman_keeps_the_host_uid_and_starts_as_container_root():
    cmd = _build("podman")
    assert "--userns=keep-id" in cmd
    user_index = cmd.index("--user")
    assert cmd[user_index + 1] == "0:0"


@pytest.mark.parametrize("cli", ["docker", "nerdctl"])
def test_docker_and_nerdctl_do_not_override_the_user(cli):
    cmd = _build(cli)
    assert "--user" not in cmd and "-u" not in cmd
    assert "--entrypoint" not in cmd


def test_there_is_no_root_bypass_option():
    with pytest.raises(SystemExit):
        container_run.parse_args(["--image", "x", "--root"])


def test_identity_on_a_posix_host(monkeypatch):
    monkeypatch.setattr(container_run.getpass, "getuser", lambda: "tester")
    monkeypatch.setattr(container_run.os, "getuid", lambda: 501, raising=False)
    monkeypatch.setattr(container_run.os, "getgid", lambda: 20, raising=False)
    assert container_run.get_host_identity() == IDENTITY


def test_native_windows_is_refused_with_wsl2_guidance(monkeypatch):
    monkeypatch.delattr(container_run.os, "getuid", raising=False)
    monkeypatch.delattr(container_run.os, "getgid", raising=False)
    with pytest.raises(container_run.HostIdentityError, match="WSL2"):
        container_run.get_host_identity()


@pytest.mark.parametrize("name", ["Mike", "first last", "DOMAIN\\user", "x" * 33])
def test_user_names_the_container_rejects_are_refused(monkeypatch, name):
    monkeypatch.setattr(container_run.getpass, "getuser", lambda: name)
    monkeypatch.setattr(container_run.os, "getuid", lambda: 501, raising=False)
    monkeypatch.setattr(container_run.os, "getgid", lambda: 20, raising=False)
    with pytest.raises(container_run.HostIdentityError, match="not valid"):
        container_run.get_host_identity()
