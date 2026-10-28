"""Tests for the git branch guard that enforces the PR workflow.

The reviewer flagged that the migrated hook could silently stop enforcing
branch protection. These tests cover both halves of that risk: the pure
decision functions (so a payload shape change cannot quietly turn the guard
into a no-op) and an end-to-end run of the script against a throwaway repo
checked out on ``main`` (so the deny path is proven to actually fire).

They live under ``services/`` because CI collects ``pytest services``; a
``scripts/tests/`` directory would be skipped by pytest.ini's testpaths.
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"


def _load(script_name: str):
    path = SCRIPTS / f"{script_name}.py"
    spec = importlib.util.spec_from_file_location(script_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_branch = _load("check_branch")


def _run(script_name: str, payload: str, cwd: Path):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / f"{script_name}.py")],
        input=payload,
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )


def _payload(command: str) -> str:
    """The shape the Copilot harness sends for a shell tool call."""
    return json.dumps({"toolName": "shell", "toolArgs": {"command": command}})


# --- decision functions -------------------------------------------------------


def test_command_is_read_from_both_payload_shapes():
    copilot = '{"toolName":"shell","toolArgs":{"command":"git status"}}'
    claude = '{"toolName":"Bash","tool_input":{"command":"git status"}}'
    assert check_branch.command_from_payload(copilot) == "git status"
    assert check_branch.command_from_payload(claude) == "git status"
    # A payload with no command at all yields "" rather than raising.
    assert check_branch.command_from_payload('{"toolName":"readFile"}') == ""
    assert check_branch.command_from_payload("not json") == ""


def test_git_write_ops_are_detected_after_a_git_token():
    for command in (
        "git commit -m 'x'",
        "git push origin feat/x",
        "git merge --no-ff feat/x",
        'git -c core.editor=true commit -m "x"',
        '"git" commit -m x',
    ):
        assert check_branch.has_git_write_op(command), command


def test_read_only_and_non_git_commands_are_allowed():
    for command in (
        "git status",
        "git log --oneline",
        "git diff main...HEAD",
        "git checkout -b feat/x",
        "npm run commit-lint",
        "echo commit",
        # A path or argument that merely contains the word must not trip it.
        "cat docs/commit-guide.md",
    ):
        assert not check_branch.has_git_write_op(command), command


# --- end-to-end: the guard actually denies on main -----------------------------


def test_commit_on_main_is_denied(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    # init -b main keeps the branch name the guard looks for on older gits too.
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True,
                   capture_output=True, text=True)

    result = _run("check_branch", _payload("git commit -m 'x'"), repo)

    assert result.returncode == 2, result.stdout + result.stderr
    decision = json.loads(result.stdout)
    assert decision["permissionDecision"] == "deny"
    assert "main" in decision["permissionDecisionReason"]


def test_commit_on_a_feature_branch_is_allowed(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True,
                   capture_output=True, text=True)
    # An initial commit is required: with an unborn HEAD, rev-parse cannot name
    # a branch and the guard correctly fails closed.
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "seed.txt"], cwd=str(repo), check=True,
                   capture_output=True, text=True)
    subprocess.run(["git", "-c", "user.email=ci@example.com", "-c", "user.name=ci",
                    "commit", "-m", "seed"], cwd=str(repo), check=True,
                   capture_output=True, text=True)
    subprocess.run(["git", "checkout", "-b", "feat/guard"], cwd=str(repo),
                   check=True, capture_output=True, text=True)

    result = _run("check_branch", _payload("git commit -m 'x'"), repo)

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {}


def test_guard_fails_closed_on_an_unborn_branch(tmp_path):
    # A brand-new repo has no commit yet, so rev-parse cannot name a branch.
    # A git write op there must be blocked rather than waved through.
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-b", "feat/unborn", str(repo)], check=True,
                   capture_output=True, text=True)

    result = _run("check_branch", _payload("git push origin feat/unborn"), repo)

    assert result.returncode == 2, result.stdout + result.stderr
    assert json.loads(result.stdout)["permissionDecision"] == "deny"


def test_guard_fails_closed_when_the_branch_is_undeterminable(tmp_path):
    # Not a git repo at all: rev-parse fails, so a git write op must be blocked
    # rather than waved through.
    outside = tmp_path / "not-a-repo"
    outside.mkdir()

    result = _run("check_branch", _payload("git push origin main"), outside)

    assert result.returncode == 2, result.stdout + result.stderr
    assert json.loads(result.stdout)["permissionDecision"] == "deny"


def test_guard_fails_closed_on_an_unparseable_command_payload(tmp_path):
    result = _run("check_branch", '{"toolArgs": {"command": ', tmp_path)

    assert result.returncode == 2, result.stdout + result.stderr
    assert json.loads(result.stdout)["permissionDecision"] == "deny"


# --- the agents guard still blocks when the agent files are missing -----------


def test_agents_guard_blocks_when_agent_files_are_missing(tmp_path):
    """check_agents.py resolves its project root from CLAUDE_PROJECT_DIR, so
    pointing it at an empty directory must produce a deny (not a crash)."""
    env_with_root = {
        "CLAUDE_PROJECT_DIR": str(tmp_path),
    }
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "check_agents.py")],
        input="{}",
        capture_output=True,
        text=True,
        env={**os.environ, **env_with_root},
        cwd=str(tmp_path),
    )

    assert result.returncode == 2, result.stdout + result.stderr
    decision = json.loads(result.stdout)
    assert decision["permissionDecision"] == "deny"
    assert ".agents" in decision["permissionDecisionReason"]


def test_agents_guard_allows_the_real_project():
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "check_agents.py")],
        input="{}",
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {}
