#!/usr/bin/env bash
# PR review wrapper — LLM config for the REVIEW agent only.
#
# Local model only (no tunnel): run_pilot.py -> llm.py routes "local/qwen-27b"
# to the local llama-server at LLAMA_SERVER_HOST:LLAMA_SERVER_PORT (default
# localhost:8080). HGM_LLM_BASE_URL is intentionally NOT set, so no remote
# endpoint is used. The coding agent never sees these vars — the review LLM
# config stays independent of the coding agent's model.
#
# Usage:
#   bash scripts/review-pr.sh <owner/repo#N> [extra run_pilot.py flags]
# Examples:
#   bash scripts/review-pr.sh compumarts/el72#12
#   bash scripts/review-pr.sh compumarts/el72#12 --dry-run
set -euo pipefail

# llama-server endpoint (llama-server must be running with qwen-27b loaded).
export LLAMA_SERVER_HOST="${LLAMA_SERVER_HOST:-localhost}"
export LLAMA_SERVER_PORT="${LLAMA_SERVER_PORT:-8080}"

# GitHub access is only required when actually posting reviews.
if ! printf '%s\n' "$@" | grep -q -- '--dry-run'; then
  : "${GITHUB_TOKEN:?GITHUB_TOKEN must be set (GitHub PAT) to post reviews. Use --dry-run to test without it.}"
fi

HGM_ROOT="$(cd "$(dirname "$0")/../../RinseRepeat/HGM/HGM-main" && pwd)"

python "$HGM_ROOT/scripts/run_pilot.py" \
  --model local/qwen-27b \
  --prs "$@"
