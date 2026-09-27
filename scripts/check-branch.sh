#!/usr/bin/env bash
# PreToolUse hook (shared by PI/Claude Code and VS Code Copilot).
# Enforces the workflow policy in .agents/AGENTS.md:
# no direct commits, pushes, or merges on `main`.
# Reads hook JSON on stdin. Exit 2 = block the tool call.
#
# Fail-closed: if this looks like a Bash tool call but the command cannot be
# extracted (e.g. python unavailable), the call is BLOCKED, not allowed.

input=$(cat)

cmd=""
if command -v python >/dev/null 2>&1; then
  cmd=$(printf '%s' "$input" | python -c 'import sys,json; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' 2>/dev/null)
fi
# Fallback parser when python is unavailable: best-effort "command" field.
if [ -z "$cmd" ]; then
  cmd=$(printf '%s' "$input" | sed -n 's/.*"command"[[:space:]]*:[[:space:]]*"\(\([^\"\\]\|\.\)\{1,\}\)".*/\1/p' | head -1)
fi

# Fail closed: an unparseable Bash payload must not slip through.
if [ -z "$cmd" ] && printf '%s' "$input" | grep -q '"command"'; then
  echo "Blocked: hook could not parse the Bash command payload (fail-closed)."
  exit 2
fi

branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)

# Token scan for git write subcommands. Catches `git commit`, extra spacing
# (`git  push`), flag variants (`git -C . commit`, `git --no-edit commit`),
# and chained commands (`foo && git push`). Conservative by design: a false
# positive blocks (the safe direction); it never allows.
contains_git_write_op() {
  local seen_git=0 tok
  for tok in $1; do
    case "$tok" in
      git) seen_git=1 ;;
      commit|push|merge)
        [ "$seen_git" = 1 ] && return 0
        ;;
    esac
  done
  return 1
}

# Fail-closed: a git write op on main — or with an undeterminable branch
# (git unavailable / not in a repo) — is blocked.
if contains_git_write_op "$cmd"; then
  if [ "$branch" = "main" ] || [ -z "$branch" ]; then
    echo "Blocked: no commits/pushes/merges on main (undeterminable branches are fail-closed). Create a feat/<name> branch off main, open a PR, and let the review agent approve it."
    exit 2
  fi
fi

exit 0
