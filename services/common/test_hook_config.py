"""Tests for the tool-call hook configuration itself.

A review pass flagged that the migrated hooks could silently stop enforcing
anything: an agent hook the harness cannot spawn or parse is a guard that
protects nothing, and the failure is invisible from inside the repo.
``test_branch_guard.py`` covers what the two guard *scripts* decide; this file
covers the *wiring* that makes them run at all, so a typo in the JSON cannot
turn branch protection into a no-op.

The expected shape comes from the Copilot SDK's native hook loader (the Rust
module inside ``@github/copilot-sdk-win32-x64/prebuilds/win32-x64/runtime.node``,
sources ``src/runtime/src/hooks_base/config.rs``), not the VS Code agent host,
which is a different loader that ignores ``version`` and ``matcher``. Observed
loader errors: ``version: Required`` / ``expected 1``, ``matcher cannot be empty``,
``Invalid matcher regex in``, and
``Specify either 'exec' (native executable) or 'bash'/'powershell'/'command'
(shell), but not both``.

They live under ``services/`` because CI collects ``pytest services``; a
``scripts/tests/`` directory would be skipped by pytest.ini's testpaths.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COPILOT_HOOKS = REPO_ROOT / ".github" / "hooks"
CLAUDE_SETTINGS = REPO_ROOT / ".claude" / "settings.json"

# Keys the Copilot SDK accepts on a single hook entry.
ENTRY_KEYS = {
    "type",
    "exec",
    "bash",
    "powershell",
    "command",
    "args",
    "cwd",
    "env",
    "timeoutSec",
    "timeout",
    "matcher",
}
SHELL_KEYS = ("bash", "powershell", "command")
# Only these two expansions exist in the Copilot loader. `${CLAUDE_PROJECT_DIR}`
# is a Claude Code token; in a Copilot hook file it reaches the shell verbatim.
COPILOT_TOKENS = ("${PLUGIN_ROOT}", "${CLAUDE_PLUGIN_ROOT}")


def _load(path: Path) -> dict:
    """Parse one hook config file and assert its top-level shape."""
    config = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(config, dict), f"{path.name} must hold one JSON object"
    assert config.get("hooks"), f"{path.name} has no 'hooks' map"
    return config


def _hook_files():
    return sorted(COPILOT_HOOKS.glob("*.json"))


def _copilot_entries() -> list[tuple[str, dict]]:
    """Every (label, entry) pair across .github/hooks/*.json."""
    entries = []
    for path in _hook_files():
        config = _load(path)
        # The most fragile line in the migration: drop `"version": 1` and the
        # loader rejects the whole file, which reads as "no hook installed".
        assert config.get("version") == 1, (
            f"{path.name}: 'version' must be exactly 1 — the Copilot hook loader "
            "reports 'version: Required, expected 1' and silently skips the file "
            "otherwise"
        )
        for name, groups in config["hooks"].items():
            assert isinstance(groups, list) and groups, f"{path.name}: {name} is empty"
            for entry in groups:
                label = f"{path.name}[{name}]"
                assert isinstance(entry, dict), f"{label} is not an object"
                entries.append((label, entry))
    assert entries, "no hook entries found in .github/hooks"
    return entries


def _command_parts(command: str) -> list[str]:
    """Split a hook command into interpreter + target.

    Quotes are stripped, and `${CLAUDE_PROJECT_DIR:-.}` is folded to `.` because
    the harness runs hooks with the project root as cwd — which is exactly what
    the default is for.
    """
    return [
        part.strip("\"").strip("'").replace("${CLAUDE_PROJECT_DIR:-.}", ".")
        for part in command.split()
    ]


def test_both_hook_files_are_present():
    names = {p.name for p in _hook_files()}
    # block-main keeps commits/pushes off main; check-agents guards the .agents
    # folder. Losing either file silently drops a guard the reviewer expects.
    assert {"block-main.json", "check-agents.json"} <= names, names


def test_copilot_hook_entries_are_well_formed():
    seen_scripts = set()
    for label, entry in _copilot_entries():
        unknown = set(entry) - ENTRY_KEYS
        assert not unknown, f"{label}: unknown hook keys {unknown}"

        assert entry.get("type") == "command", (
            f"{label}: only 'command' hooks are spawned by the Copilot loader; "
            "any other type never runs"
        )

        shell_present = [k for k in SHELL_KEYS if entry.get(k) is not None]
        has_exec = entry.get("exec") is not None
        assert bool(has_exec) != bool(shell_present), (
            f"{label}: 'exec' with a shell key trips "
            "'Specify either exec or bash/powershell/command, but not both'"
        )
        assert shell_present, f"{label}: nothing to run"
        assert len(shell_present) == 1, (
            f"{label}: more than one shell key ({shell_present}); the loader "
            "takes exactly one"
        )

        timeout = entry.get("timeoutSec")
        assert isinstance(timeout, int) and not isinstance(
            timeout, bool
        ), f"{label}: 'timeoutSec' is required by the loader"
        assert 0 < timeout <= 300, f"{label}: odd timeout {timeout}"

        matcher = entry.get("matcher")
        if matcher is not None:
            assert matcher, f"{label}: 'matcher cannot be empty'"
            re.compile(matcher)  # loader: 'Invalid matcher regex in'

        command = entry["command"]
        for token in re.findall(r"\$\{[^}]*\}", command):
            assert token in COPILOT_TOKENS, (
                f"{label}: {token} is not a Copilot token; the expansion reaches "
                "the shell literally and the guard cannot find its script"
            )
        seen_scripts.add(command)

    assert seen_scripts, "no Copilot hook command was found at all"


def test_copilot_hooks_fire_before_the_tool_call():
    # Both guards exist to stop an action, so they must sit on `preToolUse`:
    # an entry under a misspelt or later event name parses fine and never blocks
    # anything — the exact "silently disabled" shape a review pass flagged.
    for path in _hook_files():
        config = _load(path)
        assert "preToolUse" in config["hooks"], (
            f"{path.name}: events {sorted(config['hooks'])} — neither guard runs "
            "before the tool call"
        )


def test_copilot_hooks_point_at_scripts_that_exist():
    # A guard whose script moved is a guard that errors, which is exactly how
    # "silently disabled" happens. Paths resolve against the repo root, the way
    # the harness runs the hook with the project as cwd.
    for label, entry in _copilot_entries():
        parts = _command_parts(entry["command"])
        assert len(parts) >= 2, f"{label}: unhandled command {entry['command']!r}"
        script = REPO_ROOT / parts[-1]
        assert script.is_file(), f"{label}: missing {script}"
        # A bare interpreter the harness can spawn; not an absolute path baked
        # in from one machine, not a `${CLAUDE_PROJECT_DIR}` prefix.
        assert parts[0] in {"python", "python3", "py"}, (
            f"{label}: {parts[0]!r} is not a usable interpreter for "
            f"{entry['command']!r}"
        )


def test_copilot_hooks_stay_on_one_interpreter_per_file():
    for path in _hook_files():
        config = _load(path)
        interpreters = set()
        for groups in config["hooks"].values():
            for entry in groups:
                interpreters.add(entry["command"].split()[0])
        assert len(interpreters) == 1, f"{path.name}: mixed interpreters {interpreters}"


def test_guard_scripts_answer_with_one_parsable_json_decision():
    # Enforcement also depends on the harness being able to spawn the command
    # and parse its stdout: prose on stdout makes the hook error, which on some
    # hosts reads as "no guard" rather than "denied". Both guards must exit 0
    # (allow) or 2 (block) and print exactly one JSON decision object.
    for script in ("check_branch.py", "check_agents.py"):
        payload = json.dumps(
            {"toolName": "shell", "toolArgs": {"command": "git status"}},
        )
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / script)],
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(REPO_ROOT),
        )
        assert result.returncode in (0, 2), (
            f"{script}: exit {result.returncode} is neither allow (0) nor "
            f"block (2); stdout={result.stdout!r}"
        )
        decision = json.loads(result.stdout)
        assert isinstance(decision, dict), f"{script}: stdout is {result.stdout!r}"
        if result.returncode == 0:
            assert decision == {}, f"{script}: allow payload is {decision!r}"
        else:
            assert decision.get("permissionDecision") == "deny", decision
            assert decision.get("permissionDecisionReason"), decision


def test_claude_side_settings_are_kept_in_sync():
    # Claude Code reads .claude/settings.json, Copilot reads .github/hooks/*.json.
    # A guard wired on one side only is a guard half the contributors never get.
    settings = _load(CLAUDE_SETTINGS)
    events = settings["hooks"]
    assert "PreToolUse" in events, "no PreToolUse hooks in .claude/settings.json"

    commands = []
    for name, groups in events.items():
        for group in groups:
            matcher = group.get("matcher")
            assert matcher, f"{name}: Claude hook groups need a non-empty matcher"
            re.compile(matcher)
            for hook in group["hooks"]:
                assert hook["type"] == "command", hook
                assert hook["timeout"] > 0, hook
                commands.append(hook["command"])

    claude_scripts = {Path(_command_parts(command)[-1]).name for command in commands}
    copilot_scripts = {
        Path(_command_parts(entry["command"])[-1]).name
        for _, entry in _copilot_entries()
    }
    assert claude_scripts, "no Claude hook command was found"

    # Every guard must exist on the side that claims it.
    assert claude_scripts <= copilot_scripts, (
        f"Claude wires {claude_scripts}, which Copilot does not: "
        f"{claude_scripts - copilot_scripts}"
    )

    # The guard that enforces the plan-branch-PR workflow has to be wired on
    # **both** sides, because contributors use either loader. (The .agents folder
    # guard currently runs on the Copilot side only; it costs nothing to skip,
    # but a branch guard that is missing from one loader is a hole in the policy.)
    assert "check_branch.py" in claude_scripts, (
        f"Claude wires {claude_scripts} — branch protection is not enforced for "
        "Claude sessions"
    )
    assert "check_branch.py" in copilot_scripts, (
        f"Copilot wires {copilot_scripts} — branch protection is not enforced for "
        "Copilot sessions"
    )

    # `${CLAUDE_PROJECT_DIR}` is a Claude token (fine here, wrong in the Copilot
    # files above); it stays defaulted so a Claude run started from a subdirectory
    # still resolves the script.
    for command in commands:
        assert "${CLAUDE_PROJECT_DIR:-" in command, command
