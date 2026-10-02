# Plan: PR review agent — tunnel mode for the LLM endpoint

**Branch:** `chore/review-agent-tunnel` (off `main`)
**Date:** 2026-10-02
**Status:** Ready for implementation

## Goal

`scripts/review-pr.sh` currently hard-unsets `HGM_LLM_BASE_URL`/`HGM_LLM_API_KEY`
and routes `local/qwen-27b` to `localhost:8080` only. The review LLM is now
served by an OpenAI-compatible endpoint behind a Cloudflare tunnel (vLLM,
model `qwen3.8-27b`), and the local llama-server is not always running. The
wrapper must support the tunnel as an explicit, documented mode while keeping
the local-only guarantee as the default.

## Approach

- `REVIEW_LLM_MODE` env var: `local` (default — unchanged behavior) or `tunnel`.
- `tunnel` mode requires `REVIEW_LLM_BASE_URL`; optional `REVIEW_LLM_API_KEY`
  (default `local`) and `REVIEW_LLM_MODEL` (default `qwen3.8-27b`). These are
  exported as `HGM_LLM_BASE_URL`/`HGM_LLM_API_KEY` (HGM's `llm.py` already
  routes any custom base URL to the OpenAI-compatible client and **auto-streams**
  behind the tunnel, which the trycloudflare 120 s read timeout requires).
- The script header doc is updated to document both modes and the env vars.
- No change to HGM itself; no change to how reviews are posted.

## Files touched

- `plans/review-agent-tunnel.md` (this plan)
- `scripts/review-pr.sh`

## Test strategy

- Shellcheck-level sanity: `bash -n scripts/review-pr.sh`.
- `--dry-run` in `local` mode still works (no endpoint change).
- `--dry-run` in `tunnel` mode with the provided endpoint reaches
  `/v1/models` (verified manually against the live tunnel).
