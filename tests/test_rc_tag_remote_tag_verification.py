# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Michael Gardner, A Bit of Help, Inc.
"""Unit tests for ``release.release._verify_remote_annotated_tag``.

This is the rc-tag Step 5 fix. The previous implementation used
``git ls-remote --tags origin refs/tags/<tag>`` which on GitHub's
smart-HTTP protocol returns ONLY the tag-object line for exact-ref
queries and omits the peeled ``^{}`` line. That misclassified perfectly
valid annotated tags as lightweight (observed on the real adafmt
v1.0.0-rc3 invocation, 2026-06-12).

The fix uses the GitHub Git Data API instead:

  1. ``GET repos/{owner}/{repo}/git/refs/tags/<tag>`` — confirm the ref
     exists and its ``object.type`` is ``"tag"`` (annotated). A
     lightweight tag would report ``"commit"``.
  2. ``GET repos/{owner}/{repo}/git/tags/<obj-sha>`` — read
     ``object.type``, ``object.sha`` (target commit) and ``message``;
     confirm all three.

These tests mock ``subprocess.run`` so no network access or real
``gh`` CLI is required. Each test scripts the response sequence
``gh repo view`` -> ``gh api git/refs/tags`` -> ``gh api git/tags``.
"""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, List, Sequence, Tuple

import pytest

from release.release import _verify_remote_annotated_tag


# ----------------------------------------------------------------------
# Test helpers — script subprocess.run responses by command shape
# ----------------------------------------------------------------------

def _cp(stdout: str = "", returncode: int = 0, stderr: str = ""):
    """Mimic a subprocess.CompletedProcess just enough for our code."""
    return SimpleNamespace(
        stdout=stdout, stderr=stderr, returncode=returncode
    )


class _FakeRunner:
    """Scripted ``subprocess.run`` substitute.

    Each entry in ``responses`` is ``(matcher(cmd) -> bool, completed_process)``.
    The first matcher that accepts a command supplies the response. Calls
    are recorded in ``self.calls`` for assertion.
    """

    def __init__(
        self,
        responses: Sequence[Tuple[Callable[[List[str]], bool], SimpleNamespace]],
    ):
        self.responses = list(responses)
        self.calls: List[List[str]] = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        for matcher, response in self.responses:
            if matcher(cmd):
                return response
        return _cp(
            "", returncode=1, stderr=f"unexpected cmd: {cmd}"
        )


# Matchers
def _is_gh_repo_view(cmd):
    return cmd[:3] == ["gh", "repo", "view"]


def _is_gh_api_refs_tags(cmd):
    return (
        len(cmd) >= 3
        and cmd[:2] == ["gh", "api"]
        and "git/refs/tags/" in cmd[2]
    )


def _is_gh_api_git_tags(cmd):
    return (
        len(cmd) >= 3
        and cmd[:2] == ["gh", "api"]
        and "/git/tags/" in cmd[2]
        and "git/refs/tags/" not in cmd[2]
    )


# Fixtures
TARGET = "7567c5ef8587fb0e8e633e53fe8487d26696ae34"
TAG_OBJ = "9f6628e33f718a1a51ebeabc766b9a3a13f7b809"
TAG_NAME = "v1.0.0-rc3"
MSG = "adafmt v1.0.0-rc3 — third release candidate"


def _repo_view_ok():
    return _cp('"abitofhelp/adafmt"', returncode=0)


def _refs_tags_annotated_ok():
    return _cp(json.dumps({"type": "tag", "sha": TAG_OBJ}), returncode=0)


def _git_tags_ok(target_sha=TARGET, message=MSG + "\n"):
    return _cp(
        json.dumps({
            "target_type": "commit",
            "target_sha": target_sha,
            "message": message,
        }),
        returncode=0,
    )


# ----------------------------------------------------------------------
# Scenario 1: correct annotated remote tag is accepted
# ----------------------------------------------------------------------

def test_accepts_correct_annotated_remote_tag(monkeypatch):
    runner = _FakeRunner([
        (_is_gh_repo_view, _repo_view_ok()),
        (_is_gh_api_refs_tags, _refs_tags_annotated_ok()),
        (_is_gh_api_git_tags, _git_tags_ok()),
    ])
    monkeypatch.setattr("release.release.subprocess.run", runner)

    ok, diag = _verify_remote_annotated_tag(
        project_root=Path("/tmp/fake"),
        tag_name=TAG_NAME,
        expected_target_sha=TARGET,
        expected_message=MSG,
    )
    assert ok, f"expected success but got: {diag}"
    # Diagnostic includes the verified short SHAs and message length
    assert "obj=" + TAG_OBJ[:12] in diag
    assert "target=" + TARGET[:12] in diag
    assert "msg=" in diag


# ----------------------------------------------------------------------
# Scenario 2: lightweight remote tag is rejected
# ----------------------------------------------------------------------

def test_rejects_lightweight_remote_tag(monkeypatch):
    """A lightweight tag reports object.type == "commit" on the ref."""
    runner = _FakeRunner([
        (_is_gh_repo_view, _repo_view_ok()),
        (_is_gh_api_refs_tags, _cp(
            json.dumps({"type": "commit", "sha": TARGET}),
            returncode=0,
        )),
    ])
    monkeypatch.setattr("release.release.subprocess.run", runner)

    ok, diag = _verify_remote_annotated_tag(
        Path("/tmp/fake"), TAG_NAME, TARGET, MSG
    )
    assert not ok
    assert "lightweight" in diag.lower() or "'commit'" in diag


# ----------------------------------------------------------------------
# Scenario 3: annotated tag pointing to wrong target is rejected
# ----------------------------------------------------------------------

def test_rejects_annotated_tag_with_wrong_target(monkeypatch):
    """Annotated tag whose .object.sha != expected target — rejected."""
    runner = _FakeRunner([
        (_is_gh_repo_view, _repo_view_ok()),
        (_is_gh_api_refs_tags, _refs_tags_annotated_ok()),
        (_is_gh_api_git_tags, _git_tags_ok(
            target_sha="0000000000000000000000000000000000000000"
        )),
    ])
    monkeypatch.setattr("release.release.subprocess.run", runner)

    ok, diag = _verify_remote_annotated_tag(
        Path("/tmp/fake"), TAG_NAME, TARGET, MSG
    )
    assert not ok
    assert "target" in diag.lower() and "!=" in diag


# ----------------------------------------------------------------------
# Scenario 4: missing remote tag is rejected
# ----------------------------------------------------------------------

def test_rejects_missing_remote_tag(monkeypatch):
    """gh api returns rc=1 for the refs/tags lookup — caught + rejected."""
    runner = _FakeRunner([
        (_is_gh_repo_view, _repo_view_ok()),
        (_is_gh_api_refs_tags, _cp(
            stdout="", returncode=1, stderr="gh: not found (HTTP 404)"
        )),
    ])
    monkeypatch.setattr("release.release.subprocess.run", runner)

    ok, diag = _verify_remote_annotated_tag(
        Path("/tmp/fake"), TAG_NAME, TARGET, MSG
    )
    assert not ok
    assert "refs/tags" in diag.lower()
    assert "rc=1" in diag


# ----------------------------------------------------------------------
# Scenario 5: REGRESSION for the v1.0.0-rc3 partial state.
#
# We don't call ``git ls-remote`` at all in the fixed code path, but
# the function still has to succeed for a correctly-annotated tag —
# proving that the rc3 partial-state regression cannot recur, since
# exact-ref ls-remote behaviour is no longer load-bearing.
# ----------------------------------------------------------------------

def test_regression_v1_0_0_rc3_partial_state(monkeypatch):
    """With the fix, the rc3-shaped tag verifies successfully and no
    ``git ls-remote`` call is made (the formerly-buggy command)."""
    runner = _FakeRunner([
        (_is_gh_repo_view, _repo_view_ok()),
        (_is_gh_api_refs_tags, _refs_tags_annotated_ok()),
        (_is_gh_api_git_tags, _git_tags_ok()),
    ])
    monkeypatch.setattr("release.release.subprocess.run", runner)

    ok, diag = _verify_remote_annotated_tag(
        Path("/tmp/fake"), TAG_NAME, TARGET, MSG
    )
    assert ok, diag
    # No call to git ls-remote occurred
    for call in runner.calls:
        assert call[:2] != ["git", "ls-remote"], (
            f"ls-remote was reintroduced: {call}"
        )


# ----------------------------------------------------------------------
# Scenario 6: tag message mismatch is rejected
# ----------------------------------------------------------------------

def test_rejects_tag_with_wrong_message(monkeypatch):
    runner = _FakeRunner([
        (_is_gh_repo_view, _repo_view_ok()),
        (_is_gh_api_refs_tags, _refs_tags_annotated_ok()),
        (_is_gh_api_git_tags, _git_tags_ok(
            message="some completely different message\n"
        )),
    ])
    monkeypatch.setattr("release.release.subprocess.run", runner)

    ok, diag = _verify_remote_annotated_tag(
        Path("/tmp/fake"), TAG_NAME, TARGET, MSG
    )
    assert not ok
    assert "message" in diag.lower()


# ----------------------------------------------------------------------
# Scenario 7: trailing-newline normalisation (both sides) — match
# ----------------------------------------------------------------------

def test_trailing_newline_normalised_on_both_sides(monkeypatch):
    """Remote has trailing '\\n', expected has none — should match."""
    runner = _FakeRunner([
        (_is_gh_repo_view, _repo_view_ok()),
        (_is_gh_api_refs_tags, _refs_tags_annotated_ok()),
        (_is_gh_api_git_tags, _git_tags_ok(
            message="msg with trailing newline\n"
        )),
    ])
    monkeypatch.setattr("release.release.subprocess.run", runner)

    ok, diag = _verify_remote_annotated_tag(
        Path("/tmp/fake"), TAG_NAME, TARGET,
        expected_message="msg with trailing newline",  # no '\n'
    )
    assert ok, diag


# ----------------------------------------------------------------------
# Scenario 8: multi-line tag message round-trips verbatim
# ----------------------------------------------------------------------

def test_multiline_tag_message_verbatim_compare(monkeypatch):
    """Internal blank lines + paragraph structure preserved across
    normalisation; both sides match — accepted."""
    multi = "Subject line\n\nFirst body paragraph.\n\nSecond paragraph."
    runner = _FakeRunner([
        (_is_gh_repo_view, _repo_view_ok()),
        (_is_gh_api_refs_tags, _refs_tags_annotated_ok()),
        (_is_gh_api_git_tags, _git_tags_ok(message=multi + "\n")),
    ])
    monkeypatch.setattr("release.release.subprocess.run", runner)

    ok, diag = _verify_remote_annotated_tag(
        Path("/tmp/fake"), TAG_NAME, TARGET, multi
    )
    assert ok, diag


# ----------------------------------------------------------------------
# Scenario 9: gh api returns malformed JSON — fail-closed
# ----------------------------------------------------------------------

def test_malformed_refs_tags_json_fails_closed(monkeypatch):
    runner = _FakeRunner([
        (_is_gh_repo_view, _repo_view_ok()),
        (_is_gh_api_refs_tags, _cp("not valid json", returncode=0)),
    ])
    monkeypatch.setattr("release.release.subprocess.run", runner)

    ok, diag = _verify_remote_annotated_tag(
        Path("/tmp/fake"), TAG_NAME, TARGET, MSG
    )
    assert not ok
    assert "json" in diag.lower()


# ----------------------------------------------------------------------
# Scenario 10: gh repo view itself fails — fail-closed before any
# tag check
# ----------------------------------------------------------------------

def test_repo_view_failure_aborts_early(monkeypatch):
    runner = _FakeRunner([
        (_is_gh_repo_view, _cp(
            "", returncode=1, stderr="not authenticated"
        )),
    ])
    monkeypatch.setattr("release.release.subprocess.run", runner)

    ok, diag = _verify_remote_annotated_tag(
        Path("/tmp/fake"), TAG_NAME, TARGET, MSG
    )
    assert not ok
    assert "gh repo view" in diag.lower()
    # And we never reached the tag-ref or tag-object calls
    for call in runner.calls:
        assert "git/refs/tags" not in (call[2] if len(call) > 2 else "")
        assert "/git/tags/" not in (call[2] if len(call) > 2 else "")
