#!/usr/bin/env python3
"""PreToolUse hook: verify the .agents folder and skills are present.

Python port of scripts/check-agents.sh. The shell version cannot run on Windows
working trees with CRLF line endings, which made every tool call fail closed.
Exit 0 = allow, exit 2 = block. Prints a single JSON decision object on stdout,
because the Copilot harness parses command-hook stdout as JSON.
"""

import json
import os
import sys
from pathlib import Path


def emit(allow: bool, reason: str = "") -> None:
    # The harness parses stdout as one JSON object; anything else is an error.
    if allow:
        print("{}")
    else:
        print(json.dumps({"permissionDecision": "deny", "permissionDecisionReason": reason}))


def main() -> int:
    # Drain the hook event payload so the harness never sees a closed pipe.
    try:
        sys.stdin.read()
    except Exception:
        pass

    root = os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parent.parent
    agents_dir = Path(root) / ".agents"
    skills_dir = agents_dir / "skills"

    errors = 0

    if not (agents_dir / "AGENTS.md").is_file():
        print(f"ERROR: {agents_dir / 'AGENTS.md'} not found", file=sys.stderr)
        errors += 1

    if not skills_dir.is_dir():
        print(f"ERROR: {skills_dir} not found", file=sys.stderr)
        errors += 1
    else:
        for child in sorted(skills_dir.iterdir()):
            if child.is_dir() and not (child / "SKILL.md").is_file():
                print(f"ERROR: {child / 'SKILL.md'} not found (skill: {child.name})", file=sys.stderr)
                errors += 1

    if errors:
        emit(False, f"{errors} issue(s) found in the .agents folder and skills")
        return 2

    emit(True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
