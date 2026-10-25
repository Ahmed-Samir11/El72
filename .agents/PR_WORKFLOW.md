# PR Creation Workflow — El72

This document describes the end-to-end workflow for creating, reviewing, and merging PRs in the El72 repository. It is referenced from `.agents/AGENTS.md`.

## Overview

1. Plan the feature in `plans/<feature>.md`
2. Create a branch `feat/<name>` off `main`
3. Implement the feature with tests
4. Open a PR via the GitHub API (no `gh` CLI)
5. Run the HGM review agent (`scripts/review-pr.sh`)
6. Address all review findings
7. Push updates to the feature branch
8. Have a reviewer approve and merge (no self-merge)

---

## Step 1: Plan

Before writing any code, write a plan to `plans/<feature>.md` covering:
- Goal and approach
- Files to create/modify
- Test strategy
- Any architectural decisions

The plan is the contract for the feature. Implementation without an approved plan is not permitted.

---

## Step 2: Branch

Create a feature branch off `main`:

```bash
git checkout main
git pull origin main
git checkout -b feat/<name>
```

The PreToolUse hook `.github/hooks/block-main.json` blocks any git write operations on `main`. Always work on a feature branch.

---

## Step 3: Implement

- Follow the project's service-isolation rules: services communicate exclusively through Redis Streams or REST APIs; no cross-service imports (only `services/common/` is shared library).
- Write unit tests for all new code.
- Ensure all existing tests still pass.
- Follow coding standards (Black/Ruff for Python, Riverpod/GoRouter/Dio for Flutter).

---

## Step 4: Open a PR via the GitHub API

The El72 repository does not have the official `gh` CLI installed (a pip package `gh-cli` is present but `gh auth status` fails). PRs are created directly via the GitHub REST API.

### Retrieving the GitHub PAT

The GitHub Personal Access Token is stored in the Windows Credential Manager. Retrieve it with:

```bash
git credential fill
```

Input:
```
protocol=https
host=github.com
```

This outputs the username and password (PAT) for the stored credential.

### Creating the PR

Use `curl` to call the GitHub REST API:

```bash
TOKEN=$(git credential fill | grep '^password=' | sed 's/^password=//')

curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -H "Content-Type: application/json" \
  https://api.github.com/repos/Ahmed-Samir11/El72/pulls \
  -d '{
    "title": "feat: <description>",
    "head": "feat/<name>",
    "base": "main",
    "body": "<PR body with summary of changes>"
  }'
```

### PR Body Template

The PR body should include:
- Summary of changes
- Links to related plan files
- Test results
- Any known issues

Example:

```
## Summary

Implements <feature> for El72.

### Backend
- ...

### Flutter
- ...

### Tests
- All backend tests pass
- All Flutter tests pass

### Plan
- See `plans/<feature>.md`
```

---

## Step 5: Run the HGM Review Agent

The review agent is invoked via:

```bash
bash scripts/review-pr.sh <owner/repo#N>
```

The script supports two modes:
- **local** (default): Uses llama-server on `localhost:8080`
- **tunnel**: Uses an OpenAI-compatible endpoint behind a Cloudflare tunnel

```bash
# Tunnel mode
REVIEW_LLM_MODE=tunnel REVIEW_LLM_BASE_URL=https://<tunnel>/v1 \
  REVIEW_LLM_API_KEY=... \
  bash scripts/review-pr.sh <owner/repo#N>
```

The `GITHUB_TOKEN` environment variable must be set for the script to post the review to the PR:

```bash
export GITHUB_TOKEN=<pat>
bash scripts/review-pr.sh Ahmed-Samir11/El72#40
```

### Important: `scripts/review-pr.sh` line endings

The script must have **LF line endings**. CRLF breaks `set -euo pipefail`. If the script has CRLF line endings, fix with:

```bash
sed -i 's/\r$//' scripts/review-pr.sh
```

---

## Step 6: Address Review Findings

The HGM review agent posts findings as a comment on the PR. Findings are categorized as:
- **CRITICAL**: Must be fixed before merge
- **WARNING**: Should be fixed
- **INFO**: Nice-to-have

Address all CRITICAL and WARNING findings, push updates to the feature branch, and request a re-review if needed.

---

## Step 7: Push Updates

After addressing findings:

```bash
git add .
git commit -m "fix: address review findings"
git push origin feat/<name>
```

---

## Step 8: Merge (No Self-Merge)

Per project policy, a PR is not merged until it has been reviewed by another party. The author must not self-merge.

After review approval:

```bash
# The reviewer merges the PR via the GitHub API or web UI
```

Then delete the feature branch:

```bash
git branch -d feat/<name>
```

---

## Shell-Escaping Pitfalls

When passing the GitHub PAT to `curl` or the review script, be careful with shell escaping:

1. **Use single quotes** for the PAT in `curl` headers to avoid variable expansion:
   ```bash
   curl -H "Authorization: Bearer '$TOKEN'" ...
   ```

2. **Export the token** before calling the review script:
   ```bash
   export GITHUB_TOKEN="$TOKEN"
   bash scripts/review-pr.sh Ahmed-Samir11/El72#40
   ```

3. **The `gh` CLI is not reliable**: The pip-installed `gh-cli` is not the official GitHub CLI. Use direct REST API calls instead.

---

## Checklist

Before opening a PR:

- [ ] Plan written to `plans/<feature>.md`
- [ ] Branch created off `main` (`feat/<name>`)
- [ ] All tests pass (backend + Flutter)
- [ ] Code follows project standards (Black, Ruff, Riverpod)
- [ ] Database schema updated in `infra/sql/schema/postgres.sql`
- [ ] Docker configuration updated (if new service)
- [ ] Flutter localization updated (if new strings)
- [ ] PR body includes summary and test results

Before merging:

- [ ] All CRITICAL and WARNING review findings addressed
- [ ] Reviewer has approved the PR
- [ ] No self-merge

---

## Reference

- `.agents/AGENTS.md` — Project rules and conventions
- `.github/hooks/block-main.json` — PreToolUse hook blocking writes to `main`
- `.github/prompts/review-pr.prompt.md` — Review agent prompt
- `scripts/check_branch.py` — Branch enforcement script (Python; runs on Windows and POSIX)
- `scripts/check_agents.py` — Blocks edits to `.agents/` rules from outside a maintainer session
- `scripts/review-pr.sh` — HGM review agent script
