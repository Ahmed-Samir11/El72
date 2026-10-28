#!/usr/bin/env bash
#
# check-agents.sh — Verify the .agents folder and skills are present.
#
# This script is run by a Pi PreToolUse hook to ensure that the
# .agents/AGENTS.md and .agents/skills/ directory exist and are
# properly structured before any coding operations.
#
set -euo pipefail

# Resolve the repo root without relying on BASH_SOURCE (some hook runners invoke
# this script through a shell that does not set it).
REPO_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
AGENTS_DIR="$REPO_DIR/.agents"
SKILLS_DIR="$AGENTS_DIR/skills"

ERRORS=0

# --- Check .agents/AGENTS.md ---
if [[ ! -f "$AGENTS_DIR/AGENTS.md" ]]; then
  echo "ERROR: $AGENTS_DIR/AGENTS.md not found" >&2
  ERRORS=$((ERRORS + 1))
fi

# --- Check .agents/skills/ directory ---
if [[ ! -d "$SKILLS_DIR" ]]; then
  echo "ERROR: $SKILLS_DIR not found" >&2
  ERRORS=$((ERRORS + 1))
else
  # Check that each skill directory has a SKILL.md file
  for skill_dir in "$SKILLS_DIR"/*/; do
    skill_name=$(basename "$skill_dir")
    if [[ ! -f "$skill_dir/SKILL.md" ]]; then
      echo "ERROR: $skill_dir/SKILL.md not found (skill: $skill_name)" >&2
      ERRORS=$((ERRORS + 1))
    fi
  done
fi

if [[ $ERRORS -gt 0 ]]; then
  echo "ERROR: $ERRORS issue(s) found in .agents folder and skills" >&2
  exit 1
fi

echo "OK: .agents folder and skills are properly configured."
exit 0
