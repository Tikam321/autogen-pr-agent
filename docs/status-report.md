# Project Status Report

## What We've Built

### Core Agent Workflow
- **3-agent linear pipeline**: Explorer → Planner → Executor
- `fix_and_create_pr` — single end-to-end tool that reads code, applies fix (smart line-based replace with multiline fallback), creates git branch, force-pushes, auto-closes existing PRs from same branch, creates new PR
- `create_full_pr` — reusable tool for auth + commit + push + PR creation
- Auto-detects `owner`/`repo` from git remote URL
- `setup_git_auth` — configures git credentials for GitHub App (x-access-token)

### Server (Phase 2)
- **`server/auth.py`** — GitHub App JWT generation (RS256) + installation token exchange
- **`server/webhook.py`** — webhook receiver with HMAC-SHA256 signature verification, parallel request handling via `asyncio.create_task`, error-commenting on issues
- **`server/repo_manager.py`** — shallow clone (`--depth 1`) with token auth, temp directory cleanup
- **`server/runner.py`** — chdir into cloned repo, run agent workflow, extract PR URL
- **`server/app.py`** — FastAPI entry point with `/health` endpoint

### Deployment (Phase 3)
- **`Dockerfile`** — `python:3.14-slim` base, `uv` package manager, port 8000
- **`render.yaml`** — Render free-tier Docker blueprint with env vars
- **`.env.example`** — all required env vars documented

### Testing & Debugging
- **`main.py`** — CLI that accepts issue as argument, runs workflow, prints PR URL
- **`test_flow.py`** — E2E test with repo reset, stale branch cleanup, retry logic
- Live logging (`[webhook]`, `[runner]`) in server terminal

## What Works End-to-End

```
User opens issue on GitHub repo
        │
        ▼
GitHub sends webhook POST → ngrok tunnel → local server
        │
        ├── 1. Verify webhook signature (HMAC-SHA256)
        ├── 2. Generate JWT from GitHub App private key
        ├── 3. Exchange JWT for installation token
        ├── 4. git clone --depth 1 (token auth) to temp dir
        ├── 5. chdir into cloned repo
        ├── 6. Explorer agent scans codebase
        ├── 7. Planner agent creates fix plan
        ├── 8. Executor agent applies fix + creates PR
        ├── 9. PR URL returned
        ├── 10. Success → PR visible on repo
        └── 11. Failure → error comment posted on issue
        │
        ▼
   Cleanup temp directory
```

## Key Design Decisions

### Why 3 agents instead of 6?
Groq's Llama model doesn't reliably chain multiple tool calls across agents. Single `fix_and_create_pr` tool is more reliable than separate `write_file` + `git commit` + `git push` + `create PR` calls.

### Why single-line private key in `.env`?
`dotenv` library can't parse multiline values. Key is stored with `\n` escapes and decoded in `auth.py` via `.replace("\\n", "\n")`.

### Why ngrok for local testing?
GitHub webhooks need a public HTTPS URL. ngrok provides a tunnel to localhost during development. Render deployment removes this dependency.

### Why background tasks?
`asyncio.create_task` returns 200 immediately to GitHub while the agent runs in background. Prevents webhook timeout (GitHub expects response within 10s).

## What's Left

| Phase | Status | Description |
|---|---|---|
| **Deploy to Render** | ⏳ Ready | Push to GitHub → deploy via render.yaml → set env vars |
| **Make app public** | ⏳ Pending | Toggle "Public" in GitHub App settings, add install badge to README |
| **Production** | ⏳ Pending | BYOK (bring-your-own-key), monitoring, rate limiting |

## GitHub App Configuration

| Setting | Value |
|---|---|
| App ID | `4108243` |
| Webhook URL | `https://supremacy-python-polygon.ngrok-free.dev/webhook` (ngrok — temporary) |
| Permissions | Issues (read), Contents (read/write), Pull requests (read/write) |
| Events | Issues |
| Private key | `.pem` file generated, stored in `.env` |

## Test Results

- **Test repo**: `Tikam321/test-calculator`
- **PR #5 created**: Explorer → Planner → Executor pipeline ran successfully
- **Correct fix**: `a - b` → `a + b`
- **Run time**: ~9 stream messages (well within 20 message limit)
