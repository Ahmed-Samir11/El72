#!/usr/bin/env bash
# PR review wrapper — LLM config for the REVIEW agent only.
#
# Local model only (no tunnel): run_pilot.py -> llm.py routes "local/qwen-27b"
# to the local llama-server at LLAMA_SERVER_HOST:LLAMA_SERVER_PORT (default
# localhost:8080). HGM_LLM_BASE_URL / HGM_LLM_API_KEY are explicitly unset so
# an inherited remote endpoint can never override the local-only guarantee.
# The coding agent never sees these vars — the review LLM config stays
# independent of the coding agent's model.
#
# Usage:
#   bash scripts/review-pr.sh <owner/repo#N> [more refs] [extra run_pilot.py flags]
# Examples:
#   bash scripts/review-pr.sh compumarts/el72#12
#   bash scripts/review-pr.sh compumarts/el72#12 --dry-run
set -euo pipefail

# llama-server endpoint (llama-server must be running with qwen-27b loaded).
export LLAMA_SERVER_HOST="${LLAMA_SERVER_HOST:-localhost}"
export LLAMA_SERVER_PORT="${LLAMA_SERVER_PORT:-8080}"

# Local-only guarantee: strip any inherited remote LLM endpoint config.
unset HGM_LLM_BASE_URL HGM_LLM_API_KEY

# HGM checkout location — overridable, with a clear error if missing.
HGM_ROOT="${HGM_ROOT:-$(cd "$(dirname "$0")/../../RinseRepeat/HGM/HGM-main" 2>/dev/null && pwd)}"
if [ -z "$HGM_ROOT" ] || [ ! -f "$HGM_ROOT/scripts/run_pilot.py" ]; then
  echo "Error: HGM review agent not found at '${HGM_ROOT}'. Set HGM_ROOT to the HGM-main checkout." >&2
  exit 1
fi

# GitHub access is only required when actually posting reviews.
if ! printf '%s\n' "$@" | grep -q -- '--dry-run'; then
  : "${GITHUB_TOKEN:?GITHUB_TOKEN must be set (GitHub PAT) to post reviews. Use --dry-run to test without it.}"
fi

# Split args deterministically: PR refs (non-flag tokens) go to --prs; flags
# pass through untouched — including values for valued flags, so ordering no
# longer matters and a flag can never be swallowed into --prs.
VALUED_FLAGS=(--output --confidence-threshold --prompts-dir --feedback-db --pilot-session --log-level)

is_valued_flag() {
  local f=$1 v
  for v in "${VALUED_FLAGS[@]}"; do
    [ "$f" = "$v" ] && return 0
  done
  return 1
}

PRS=()
FLAGS=()
expect_value=0
for arg in "$@"; do
  if [ "$expect_value" = 1 ]; then
    FLAGS+=("$arg")
    expect_value=0
    continue
  fi
  case "$arg" in
    -*)
      FLAGS+=("$arg")
      if is_valued_flag "$arg"; then
        expect_value=1
      fi
      ;;
    *)
      PRS+=("$arg")
      ;;
  esac
done

if [ "${#PRS[@]}" -eq 0 ]; then
  echo "Usage: review-pr.sh <owner/repo#N> [more refs] [run_pilot.py flags]" >&2
  exit 1
fi

python "$HGM_ROOT/scripts/run_pilot.py" \
  --model local/qwen-27b \
  --prs "${PRS[@]}" \
  ${FLAGS[@]+"${FLAGS[@]}"}
