# PR Autogen Agent

A GitHub App that auto-fixes issues by creating PRs using a multi-agent AutoGen workflow, deployed on Render.

## Architecture

```
GitHub Issue (opened)
        │
        ▼  webhook POST
┌─────────────────────────────────┐
│       FastAPI Server (Render)   │
│                                 │
│  1. Verify HMAC signature       │
│  2. Exchange JWT → install token│
│  3. Clone repo (──depth 1)      │
│  4. Run 3-agent graph           │
│  5. Create PR, comment on issue │
│  6. Cleanup temp dir            │
└─────────────┬───────────────────┘
              │
              ▼
     ┌───────────────────────┐
     │    3-Agent Pipeline   │
     │  GraphFlow (DAG)      │
     │                       │
     │  ┌──────────┐         │
     │  │ Explorer │─►files  │
     │  └──────────┘         │
     │  ┌──────────┐         │
     │  │ Planner  │─►plan   │
     │  └──────────┘         │
     │  ┌──────────┐         │
     │  │ Executor │─►PR     │
     │  └──────────┘         │
     └───────────────────────┘
              │
              ▼
        PR created on
        target repo
```

## Agents

| Agent | Tools | Role |
|---|---|---|
| **Explorer** | `list_directory`, `read_file`, `grep_search` | Scans the codebase for files relevant to the issue |
| **Planner** | _(none — pure LLM)_ | Creates a step-by-step fix plan from exploration results |
| **Executor** | `fix_and_create_pr` | Reads file, applies line-based replace, commits, force-pushes, creates PR with auto-close of old PRs from same branch |

## Project Structure

```
pr-autogen-agent/
├── agents/
│   ├── explorer.py       # Scans codebase for relevant files
│   ├── planner.py        # Creates fix plan (no tools)
│   └── executor.py       # fix_and_create_pr tool
├── tools/
│   ├── file_tools.py     # read_file, write_file, grep_search, list_directory
│   └── git_tools.py      # fix_and_create_pr, create_full_pr, create_pr, setup_git_auth
├── server/
│   ├── app.py            # FastAPI entry point + health endpoint
│   ├── auth.py           # JWT → installation token exchange
│   ├── webhook.py        # HMAC signature verification + issue handler
│   ├── repo_manager.py   # Clone (──depth 1, token auth) + cleanup + comment_on_issue
│   └── runner.py         # chdir into cloned repo + run agent workflow
├── docs/
│   ├── internal-architecture.md   # Full architecture deep-dive
│   ├── status-report.md           # Current project status
│   └── deployment-action-plan.md  # Render deployment guide
├── config.py             # get_model_client() → Mistral AI client
├── workflow.py           # 3-node DiGraph team definition
├── main.py               # CLI entry point for local testing
├── Dockerfile            # python:3.14-slim + git + uv
├── render.yaml           # Render blueprint (free tier)
├── pyproject.toml        # uv-managed dependencies
├── .env.example          # Required env vars template
└── .gitignore
```

## Tech Stack

| Component | Technology |
|---|---|
| **Agent Framework** | AutoGen AgentChat 0.7.x (`autogen-agentchat`) |
| **LLM Provider** | Mistral AI (`mistral-medium`) |
| **Model Client** | `OpenAIChatCompletionClient` |
| **Orchestration** | `GraphFlow` + `DiGraph` — linear DAG (explorer → planner → executor) |
| **Git Integration** | `FunctionTool` wrappers via subprocess |
| **Server** | FastAPI + uvicorn |
| **Deployment** | Docker → Render (free tier) |
| **Auth** | GitHub App JWT + installation tokens |
| **Secrets** | `.env` (ignored by git) |
| **Python** | 3.14 |
| **Package Manager** | `uv` |

## Setup

```bash
git clone https://github.com/Tikam321/autogen-pr-agent
cd pr-autogen-agent
uv sync
cp .env.example .env
# Edit .env with your secrets (see below)
```

### Required Environment Variables

| Variable | Description |
|---|---|
| `MISTRAL_API_KEY` | Mistral AI API key for LLM calls |
| `GITHUB_TOKEN` | GitHub personal access token (local CLI testing) |
| `GITHUB_APP_ID` | GitHub App ID (4108243) |
| `GITHUB_PRIVATE_KEY` | GitHub App private key (single line, `\n` for newlines) |
| `GITHUB_WEBHOOK_SECRET` | Webhook HMAC secret |

> **Note:** `GITHUB_PRIVATE_KEY` must be a single line with `\n` to represent newlines. Dotenv cannot parse multi-line values.

## Usage

```bash
# CLI: pass issue as argument
uv run python main.py "The add function in calculator.py returns a - b instead of a + b"

# CLI: pipe issue from file
uv run python main.py < issue.txt

# Local server
uv run python -m uvicorn server.app:app --port 8000

# With ngrok (for GitHub webhook testing)
ngrok http 8000
```

## Status

| Area | Status | Details |
|---|---|---|
| **Core Agent Flow** | ✅ Done | 3-agent graph, fix_and_create_pr tool, CLI entry |
| **Server** | ✅ Done | FastAPI, auth, webhook, clone/cleanup, runner |
| **Deploy** | ✅ Live | `https://pr-autogen-agent.onrender.com` |
| **Error Comments** | ✅ Done | Failed agent runs comment on the issue |
| **BYOK** | ⏳ Pending | Bring-your-own-key for LLM provider |

## Gotchas

- `tools` goes on `AssistantAgent`, **not** on `OpenAIChatCompletionClient`
- Multi-task input: `task=[TextMessage(...)]`, not raw strings
- GitHub private key in `.env`: single line with `\n` escapes
- Docker image needs `apt-get install git` (not in `python:3.14-slim`)
- `setup_git_auth` must set `user.name` and `user.email` before `git commit`
