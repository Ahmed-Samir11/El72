#!/usr/bin/env bash
# PreToolUse hook (shared by PI/Claude Code and VS Code Copilot).
# Enforces the workflow policy in .agents/AGENTS.md:
# no direct commits, pushes, or merges on `main`.
# Reads hook JSON on stdin. Exit 2 = block the tool call.
input=$(cat)
cmd=$(echo "$input" | python -c "import sys,json; print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" 2>/dev/null)

branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)

if [ "$branch" = "main" ]; then
  if echo "$cmd" | grep -qE 'git (push|commit|merge)'; then
    echo "Blocked: no commits/pushes/merges on main. Create a feat/<name> branch off main, open a PR, and let the review agent approve it."
    exit 2
  fi
fi

exit 0
