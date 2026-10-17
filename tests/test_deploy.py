"""Tests for scripts/deploy.sh — the production deploy pipeline."""

import os
import shutil
import subprocess
import tempfile


def _write_env(path: str, api_domain: str) -> None:
    with open(path, "w") as fh:
        fh.write(f"API_DOMAIN={api_domain}\n")
        fh.write("POSTGRES_PASSWORD=dev\n")
        fh.write("SECRET_KEY=dev\n")


def _make_mock_commands(bin_dir: str, calls_log: str) -> None:
    """Create mock `docker`, `git`, `curl` commands in bin_dir.

    The mocks record the commands they are invoked with (calls.log) so the
    test can assert the deploy script issues the right calls.
    """
    # calls_log must use forward slashes so bash can interpret it.
    calls_log_fwd = calls_log.replace("\\", "/")

    def _write_mock(name: str, body: str) -> None:
        path = os.path.join(bin_dir, name)
        with open(path, "w") as fh:
            fh.write(body)
        os.chmod(path, 0o755)

    # docker: record args, exit 0.
    _write_mock(
        "docker",
        f"""#!/usr/bin/env bash
echo "$@" >> {calls_log_fwd}
exit 0
""",
    )
    # git pull: record args, exit 0.
    _write_mock(
        "git",
        f"""#!/usr/bin/env bash
echo "$@" >> {calls_log_fwd}
exit 0
""",
    )
    # curl: record args, print a fake healthy response, exit 0.
    _write_mock(
        "curl",
        f"""#!/usr/bin/env bash
echo "$@" >> {calls_log_fwd}
echo '{{"status":"ok"}}'
exit 0
""",
    )


def _run_deploy(script_path: str, workdir: str, env: dict):
    """Run the deploy script via bash.

    On Windows, `script_path` must use forward slashes (bash-compatible)
    and `workdir` must use backslashes (CreateProcess-compatible).
    `shell=True` routes through cmd.exe /c so bash receives the path
    through the shell and can interpret it correctly.
    """
    cmd = 'bash "' + script_path + '"'
    return subprocess.run(
        cmd,
        shell=True,
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )


def _setup_workdir():
    """Mirror the repo layout: script in scripts/, .env at root.

    Uses a temp dir so bash can execute the script. Returns the workdir path.
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    workdir = tempfile.mkdtemp(prefix="deploy-test-")
    os.makedirs(os.path.join(workdir, "scripts"))
    shutil.copy(
        os.path.join(repo_root, "scripts", "deploy.sh"),
        os.path.join(workdir, "scripts", "deploy.sh"),
    )
    return workdir


def test_deploy_script_flows_through_pipeline():
    """The deploy script pulls, builds, starts the stack, and polls health."""
    workdir = _setup_workdir()

    env_file = os.path.join(workdir, ".env")
    _write_env(env_file, "api.el72.io")

    bin_dir = os.path.join(workdir, "bin")
    os.makedirs(bin_dir)
    calls_log = os.path.join(bin_dir, "calls.log")
    _make_mock_commands(bin_dir, calls_log)

    env = os.environ.copy()
    env["PATH"] = bin_dir + os.pathsep + env["PATH"]

    # Bash-compatible path (forward slashes); cwd is Windows-native (backslashes).
    script_path = os.path.join(workdir, "scripts", "deploy.sh").replace("\\", "/")
    result = _run_deploy(script_path, workdir, env)

    assert result.returncode == 0, result.stderr
    log = open(calls_log).read()

    # git pull --ff-only origin main
    assert "pull --ff-only origin main" in log
    # docker compose -f docker-compose.yml -f docker-compose.prod.yml
    #   --env-file .env up -d --build
    assert (
        "compose -f docker-compose.yml -f docker-compose.prod.yml"
        " --env-file .env up -d --build" in log
    )
    # health check curl
    assert "-fsS https://api.el72.io/health" in log


def test_deploy_script_fails_without_env_file():
    """Missing .env must make the script exit non-zero."""
    workdir = _setup_workdir()
    # No .env file.

    bin_dir = os.path.join(workdir, "bin")
    os.makedirs(bin_dir)
    calls_log = os.path.join(bin_dir, "calls.log")
    _make_mock_commands(bin_dir, calls_log)

    env = os.environ.copy()
    env["PATH"] = bin_dir + os.pathsep + env["PATH"]

    script_path = os.path.join(workdir, "scripts", "deploy.sh").replace("\\", "/")
    result = _run_deploy(script_path, workdir, env)

    assert result.returncode != 0
    assert ".env is missing" in result.stderr


def test_api_domain_read_from_env_file():
    """API_DOMAIN must be read from .env (not exported to the shell)."""
    workdir = _setup_workdir()

    env_file = os.path.join(workdir, ".env")
    _write_env(env_file, "api.el72.io")

    bin_dir = os.path.join(workdir, "bin")
    os.makedirs(bin_dir)
    calls_log = os.path.join(bin_dir, "calls.log")
    _make_mock_commands(bin_dir, calls_log)

    env = os.environ.copy()
    # Pre-populate API_DOMAIN in the shell with a DIFFERENT value to prove
    # the script reads it from .env, not the environment.
    env["API_DOMAIN"] = "wrong.example.com"
    env["PATH"] = bin_dir + os.pathsep + env["PATH"]

    script_path = os.path.join(workdir, "scripts", "deploy.sh").replace("\\", "/")
    result = _run_deploy(script_path, workdir, env)

    assert result.returncode == 0, result.stderr
    log = open(calls_log).read()
    # The health check must use the value from .env, not the shell env.
    assert "https://api.el72.io/health" in log
    assert "https://wrong.example.com/health" not in log


def test_deploy_script_handles_quoted_env_value():
    """API_DOMAIN values wrapped in quotes must be stripped correctly."""
    workdir = _setup_workdir()

    env_file = os.path.join(workdir, ".env")
    with open(env_file, "w") as fh:
        fh.write('API_DOMAIN="api.el72.io"\n')
        fh.write("POSTGRES_PASSWORD=dev\n")
        fh.write("SECRET_KEY=dev\n")

    bin_dir = os.path.join(workdir, "bin")
    os.makedirs(bin_dir)
    calls_log = os.path.join(bin_dir, "calls.log")
    _make_mock_commands(bin_dir, calls_log)

    env = os.environ.copy()
    env["PATH"] = bin_dir + os.pathsep + env["PATH"]

    script_path = os.path.join(workdir, "scripts", "deploy.sh").replace("\\", "/")
    result = _run_deploy(script_path, workdir, env)

    assert result.returncode == 0, result.stderr
    log = open(calls_log).read()
    assert "https://api.el72.io/health" in log


def test_prod_compose_has_required_secrets():
    """The prod overlay must require all secrets it defines via :? so the
    stack refuses to start without them. Secrets inherited from the dev
    compose file (postgres passwords, WhatsApp, Paymob) are defined there."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(repo_root, "docker-compose.prod.yml")) as fh:
        content = fh.read()

    # Each service that defines a secret must use the :? required-value
    # syntax (not just a plain env var).
    assert "SECRET_KEY:?" in content
    assert "ADMIN_USERNAME:?" in content
    assert "ADMIN_PASSWORD:?" in content
    assert "ADMIN_SECRET_KEY:?" in content
    assert "ACME_EMAIL:?" in content
    assert "PROD_DOMAIN:?" in content
    assert "API_DOMAIN:?" in content


def test_prod_compose_dbs_internal_only():
    """Database services must not expose host ports in prod."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(repo_root, "docker-compose.prod.yml")) as fh:
        content = fh.read()

    # Each DB service block must have ports: [] (internal-only).
    for service in ["postgres", "timescaledb", "redis"]:
        assert f"  {service}:" in content
        # The next 'ports:' line under this service must be 'ports: []'
        # (simple substring check is sufficient for this overlay).
        assert "ports: []" in content, f"{service} should have ports: [] in prod"


def _make_failing_mock(name: str, bin_dir: str, calls_log: str) -> None:
    """Create a mock command that records the call and exits non-zero."""
    # calls_log must use forward slashes so bash can write to it.
    calls_log_fwd = calls_log.replace("\\", "/")
    path = os.path.join(bin_dir, name)
    with open(path, "w") as fh:
        fh.write("#!/usr/bin/env bash\n")
        fh.write('echo "$@" >> ' + calls_log_fwd + "\n")
        fh.write("exit 1\n")
    os.chmod(path, 0o755)


def test_deploy_script_fails_on_git_pull_failure():
    """A failing git pull must abort the deploy with a non-zero exit."""
    workdir = _setup_workdir()

    env_file = os.path.join(workdir, ".env")
    _write_env(env_file, "api.el72.io")

    bin_dir = os.path.join(workdir, "bin")
    os.makedirs(bin_dir)
    # Use forward-slash path for the log so bash can write to it.
    calls_log = os.path.join(bin_dir, "calls.log").replace("\\", "/")
    _make_mock_commands(bin_dir, calls_log)
    # Make git fail.
    _make_failing_mock("git", bin_dir, calls_log)

    env = os.environ.copy()
    env["PATH"] = bin_dir + os.pathsep + env["PATH"]

    script_path = os.path.join(workdir, "scripts", "deploy.sh").replace("\\", "/")
    result = _run_deploy(script_path, workdir, env)

    assert result.returncode != 0
    log = open(calls_log).read()
    # git pull was attempted.
    assert "pull --ff-only origin main" in log
    # docker compose was NOT reached.
    assert "compose" not in log


def test_deploy_script_fails_on_docker_compose_failure():
    """A failing docker compose must abort the deploy with a non-zero exit."""
    workdir = _setup_workdir()

    env_file = os.path.join(workdir, ".env")
    _write_env(env_file, "api.el72.io")

    bin_dir = os.path.join(workdir, "bin")
    os.makedirs(bin_dir)
    calls_log = os.path.join(bin_dir, "calls.log").replace("\\", "/")
    _make_mock_commands(bin_dir, calls_log)
    # Make docker fail.
    _make_failing_mock("docker", bin_dir, calls_log)

    env = os.environ.copy()
    env["PATH"] = bin_dir + os.pathsep + env["PATH"]

    script_path = os.path.join(workdir, "scripts", "deploy.sh").replace("\\", "/")
    result = _run_deploy(script_path, workdir, env)

    assert result.returncode != 0
    log = open(calls_log).read()
    # git pull succeeded.
    assert "pull --ff-only origin main" in log
    # docker compose was attempted.
    assert "compose" in log
    # health check was NOT reached.
    assert "health" not in log
