#!/usr/bin/env bash
# PR review wrapper — LLM config for the REVIEW agent only.
#
# The coding agent never sees these vars — the review LLM config stays
# independent of the coding agent's model.
#
# Two modes (REVIEW_LLM_MODE):
#
#   local (default)  — llama-server only, no tunnel: run_pilot.py routes
#                      "local/qwen-27b" to LLAMA_SERVER_HOST:LLAMA_SERVER_PORT
#                      (default localhost:8080). HGM_LLM_BASE_URL / HGM_LLM_API_KEY
#                      are explicitly unset so an inherited remote endpoint can
#                      never override the local-only guarantee.
#
#   tunnel           — an OpenAI-compatible endpoint behind a Cloudflare
#                      tunnel (e.g. vLLM serving qwen3.8-27b). Requires
#                      REVIEW_LLM_BASE_URL; optional REVIEW_LLM_API_KEY
#                      (default "local") and REVIEW_LLM_MODEL (default
#                      "qwen3.8-27b"). HGM's llm.py auto-streams for custom
#                      base URLs, which the trycloudflare proxy's 120 s read
#                      timeout requires.
#
# Usage:
#   bash scripts/review-pr.sh <owner/repo#N> [more refs] [extra run_pilot.py flags]
# Examples:
#   bash scripts/review-pr.sh compumarts/el72#12
#   REVIEW_LLM_MODE=tunnel \
#     REVIEW_LLM_BASE_URL=https://<tunnel>.trycloudflare.com/v1 \
#     REVIEW_LLM_API_KEY=sk-... \
#     bash scripts/review-pr.sh compumarts/el72#12
set -euo pipefail

# Review LLM mode: local (default) or tunnel. Any other value is a
# misconfiguration (e.g. a "TUNNEL" typo) — fail loudly instead of
# silently falling back to a local server that may be down.
REVIEW_LLM_MODE="${REVIEW_LLM_MODE:-local}"
if [ "$REVIEW_LLM_MODE" != "local" ] && [ "$REVIEW_LLM_MODE" != "tunnel" ]; then
  echo "Error: REVIEW_LLM_MODE must be 'local' or 'tunnel' (got '$REVIEW_LLM_MODE')." >&2
  exit 1
fi

if [ "$REVIEW_LLM_MODE" = "tunnel" ]; then
  # Tunnel mode: pass the custom OpenAI-compatible endpoint through to HGM.
  : "${REVIEW_LLM_BASE_URL:?REVIEW_LLM_MODE=tunnel requires REVIEW_LLM_BASE_URL (e.g. https://<tunnel>.trycloudflare.com/v1)}"
  case "$REVIEW_LLM_BASE_URL" in
    http://*|https://*) ;;
    *)
      echo "Error: REVIEW_LLM_BASE_URL must be an http(s) URL (got '$REVIEW_LLM_BASE_URL')." >&2
      exit 1
      ;;
  esac
  export HGM_LLM_BASE_URL="$REVIEW_LLM_BASE_URL"
  # The default key 'local' suits unauthenticated vLLM endpoints; a tunnel
  # that requires real auth must set REVIEW_LLM_API_KEY explicitly.
  export HGM_LLM_API_KEY="${REVIEW_LLM_API_KEY:-local}"
  REVIEW_MODEL="${REVIEW_LLM_MODEL:-qwen3.8-27b}"
else
  # Local-only guarantee: strip any inherited remote LLM endpoint config.
  unset HGM_LLM_BASE_URL HGM_LLM_API_KEY
  REVIEW_MODEL="local/qwen-27b"

  # llama-server endpoint (llama-server must be running with qwen-27b
  # loaded) — only relevant in local mode.
  export LLAMA_SERVER_HOST="${LLAMA_SERVER_HOST:-localhost}"
  export LLAMA_SERVER_PORT="${LLAMA_SERVER_PORT:-8080}"
fi

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
  --model "$REVIEW_MODEL" \
  --prs "${PRS[@]}" \
  ${FLAGS[@]+"${FLAGS[@]}"}
