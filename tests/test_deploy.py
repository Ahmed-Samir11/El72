"""Tests for scripts/deploy.sh — the production deploy pipeline."""

import os
import shutil
import subprocess

import pytest


def _write_env(path: str, api_domain: str) -> None:
    with open(path, "w") as fh:
        fh.write(f"API_DOMAIN={api_domain}\n")
        fh.write("POSTGRES_PASSWORD=dev\n")
        fh.write("SECRET_KEY=dev\n")


def _make_mock_commands(bin_dir: str, api_domain: str) -> str:
    """Create mock `docker`, `git`, `curl` commands in bin_dir.

    The mocks record the commands they are invoked with (calls.log) so the
    test can assert the deploy script issues the right calls.
    """
    calls_log = os.path.join(bin_dir, "calls.log")

    def _write_mock(name: str, body: str) -> None:
        path = os.path.join(bin_dir, name)
        with open(path, "w") as fh:
            fh.write(body)
        os.chmod(path, 0o755)

    # docker: record args, exit 0.
    _write_mock(
        "docker",
        f"""#!/usr/bin/env bash
echo \"$@\" >> {calls_log}
exit 0
""",
    )
    # git pull: record, exit 0.
    _write_mock(
        "git",
        f"""#!/usr/bin/env bash
echo \"$@\" >> {calls_log}
exit 0
""",
    )
    # curl: record, print a fake healthy response for the health URL, exit 0.
    _write_mock(
        "curl",
        f"""#!/usr/bin/env bash
echo \"$@\" >> {calls_log}
if [[ \"$*\" == *\"{api_domain}/health\"* ]]; then
  echo '{{"status":"ok"}}'
  exit 0
fi
exit 7
""",
    )
    return calls_log


def _win_to_cygwin_path(path: str) -> str:
    """Convert a Windows absolute path to a Cygwin path for bash."""
    path = path.replace("\\", "/")
    if len(path) >= 2 and path[1] == ":":
        drive = path[0].lower()
        path = f"/{drive}{path[2:]}"
    return path


def _run_deploy(script_path: str, workdir: str, env: dict):
    """Run the deploy script.

    Uses shell=True (cmd.exe /c on Windows) so bash receives the path
    through the shell and can interpret it correctly.
    """
    return subprocess.run(
        f'bash "{script_path}"',
        shell=True,
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )


def _setup_workdir():
    """Mirror the repo layout: script in scripts/, .env at root.

    Uses a temp dir under the user profile so bash can execute the script.
    Returns the Windows workdir path (forward slashes).
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    win_workdir = os.path.join(
        os.path.expanduser("~\\AppData\\Local\\Temp"), "deploy-test"
    ).replace("\\", "/")
    os.makedirs(os.path.join(win_workdir, "scripts"), exist_ok=True)
    shutil.copy(
        os.path.join(repo_root, "scripts", "deploy.sh"),
        os.path.join(win_workdir, "scripts", "deploy.sh"),
    )
    return win_workdir


def test_deploy_script_flows_through_pipeline():
    """The deploy script pulls, builds, starts the stack, and polls health."""
    win_workdir = _setup_workdir()

    env_file = win_workdir + "/.env"
    _write_env(env_file, "api.el72.io")

    bin_dir = win_workdir + "/bin"
    os.makedirs(bin_dir, exist_ok=True)
    calls_log = _make_mock_commands(bin_dir, "api.el72.io")

    env = os.environ.copy()
    # Cygwin bash expects ':' as PATH separator and forward slashes.
    env["PATH"] = _win_to_cygwin_path(bin_dir) + ":" + env["PATH"]

    script_path = win_workdir + "/scripts/deploy.sh"
    result = _run_deploy(script_path, win_workdir, env)

    assert result.returncode == 0, result.stderr
    log = open(calls_log).read()

    # git pull --ff-only origin main
    assert "pull --ff-only origin main" in log
    # docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env up -d --build
    assert (
        "compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env up -d --build"
        in log
    )
    # health check curl
    assert "-fsS https://api.el72.io/health" in log


def test_deploy_script_fails_without_env_file():
    """Missing .env must make the script exit non-zero."""
    win_workdir = _setup_workdir()
    # Remove .env if present.
    env_file = win_workdir + "/.env"
    if os.path.exists(env_file):
        os.remove(env_file)

    bin_dir = win_workdir + "/bin"
    os.makedirs(bin_dir, exist_ok=True)
    _make_mock_commands(bin_dir, "api.el72.io")

    env = os.environ.copy()
    # Cygwin bash expects ':' as PATH separator and forward slashes.
    env["PATH"] = _win_to_cygwin_path(bin_dir) + ":" + env["PATH"]

    script_path = win_workdir + "/scripts/deploy.sh"
    result = _run_deploy(script_path, win_workdir, env)

    assert result.returncode != 0
    assert ".env is missing" in result.stderr


def test_api_domain_read_from_env_file():
    """API_DOMAIN must be read from .env (not exported to the shell)."""
    win_workdir = _setup_workdir()

    env_file = win_workdir + "/.env"
    _write_env(env_file, "api.el72.io")

    bin_dir = win_workdir + "/bin"
    os.makedirs(bin_dir, exist_ok=True)
    calls_log = _make_mock_commands(bin_dir, "api.el72.io")

    env = os.environ.copy()
    # Pre-populate API_DOMAIN in the shell with a DIFFERENT value to prove
    # the script reads it from .env, not the environment.
    env["API_DOMAIN"] = "wrong.example.com"
    # Cygwin bash expects ':' as PATH separator and forward slashes.
    env["PATH"] = _win_to_cygwin_path(bin_dir) + ":" + env["PATH"]

    script_path = win_workdir + "/scripts/deploy.sh"
    result = _run_deploy(script_path, win_workdir, env)

    assert result.returncode == 0, result.stderr
    log = open(calls_log).read()
    # The health check must use the value from .env, not the shell env.
    assert "https://api.el72.io/health" in log
    assert "https://wrong.example.com/health" not in log
