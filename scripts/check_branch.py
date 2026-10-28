#!/usr/bin/env python3
"""PreToolUse hook: forbid git write operations on `main`.

Python port of scripts/check-branch.sh so the guard also works on Windows
working trees with CRLF line endings. Reads the hook JSON payload on stdin.
Exit 0 = allow, exit 2 = block. Fail-closed: an unparseable payload or an
undeterminable branch blocks any git write op.
"""

import json
import subprocess
import sys


def command_from_payload(payload: str) -> str:
    try:
        data = json.loads(payload)
    except ValueError:
        return ""
    # Copilot harness sends toolName/toolArgs; the Claude alias sends tool_input.
    for key in ("toolArgs", "tool_input"):
        args = data.get(key) or {}
        if isinstance(args, dict):
            command = args.get("command")
            if isinstance(command, str):
                return command
    return ""


def has_git_write_op(command: str) -> bool:
    seen_git = False
    for token in command.split():
        token = token.strip("\"'")
        if token == "git":
            seen_git = True
        elif token in {"commit", "push", "merge"} and seen_git:
            return True
    return False


def current_branch() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def emit(allow: bool, reason: str = "") -> None:
    # The harness parses stdout as one JSON object; anything else is an error.
    if allow:
        print("{}")
    else:
        print(json.dumps({"permissionDecision": "deny", "permissionDecisionReason": reason}))


def main() -> int:
    payload = sys.stdin.read()
    command = command_from_payload(payload)

    # Fail closed: a tool payload carrying a command we could not parse.
    if not command and '"command"' in payload:
        emit(False, "Blocked: hook could not parse the tool command payload (fail-closed).")
        return 2

    if has_git_write_op(command):
        branch = current_branch()
        if branch == "main" or not branch:
            emit(
                False,
                "Blocked: no commits/pushes/merges on main (undeterminable branches "
                "are fail-closed). Create a feat/<name> branch off main, open a PR, "
                "and let the review agent approve it.",
            )
            return 2

    emit(True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
