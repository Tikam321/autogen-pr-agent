# pr-autogen-agent

A GitHub App that auto-fixes issues by creating PRs using a multi-agent AutoGen workflow.

## Architecture (current)

```
Issue (CLI or GitHub issue webhook)
        │
        ▼
┌──────────────────────────────┐
│       3-Agent Linear Flow    │
│                              │
│  ┌──────────┐   ┌──────────┐ │
│  │ Explorer │──►│ Planner  │─│──► messages
│  └──────────┘   └──────────┘ │
│                     │        │
│                     ▼        │
│              ┌──────────┐    │
│              │ Executor │    │
│              └────┬─────┘    │
│                   │          │
│            fix_and_create_pr │
└───────────────────┼──────────┘
                    ▼
        ┌─────────────────────┐
        │  PR created on      │
        │  target repo        │
        └─────────────────────┘
```

## Agents

| Agent | Tools | Purpose |
|---|---|---|
| **Explorer** | `list_directory`, `read_file`, `grep_search` | Scans the codebase for files relevant to the issue |
| **Planner** | _(none — pure LLM)_ | Creates a step-by-step fix plan from exploration |
| **Executor** | `fix_and_create_pr` | Reads file, applies fix, commits, force-pushes, creates PR (single tool) |

## Flow

1. **Explorer** reads the codebase, finds relevant files
2. **Planner** creates a fix plan from explorer's findings
3. **Executor** calls `fix_and_create_pr(search_text, replace_with, commit_message)` — a single end-to-end tool that reads the file, does a smart line-based replace (with multiline fallback), commits, force-pushes to `fix-issue-<timestamp>`, auto-closes any existing PR from that branch, and creates a new PR

## Deployment

```
GitHub Issue (opened)
        │
        ▼  webhook POST
┌───────────────────┐
│  FastAPI Server   │
│  (Render.com)     │
│                   │
│  verify signature │
│  get inst. token  │
│  clone repo       │
│  run 3 agents     │
│  create PR        │
│  cleanup temp dir │
└───────────────────┘
        │
        ▼
   PR created on repo
```

## Project Structure

```
pr-autogen-agent/
├── agents/
│   ├── __init__.py
│   ├── explorer.py       # Scans codebase for relevant files
│   ├── planner.py        # Creates fix plan (no tools)
│   └── executor.py       # fix_and_create_pr tool
├── tools/
│   ├── __init__.py
│   ├── file_tools.py     # read_file, write_file, edit_file, grep_search, list_directory
│   └── git_tools.py      # fix_and_create_pr, create_full_pr, setup_git_auth
├── server/
│   ├── __init__.py
│   ├── app.py            # FastAPI entry point
│   ├── auth.py           # JWT → installation token
│   ├── webhook.py        # Signature verification + issue handler
│   ├── repo_manager.py   # Clone (depth 1) + cleanup
│   └── runner.py         # chdir + agent workflow
├── docs/                 # Architecture docs
├── config.py             # Model client factory
├── workflow.py           # 3-node linear team flow
├── test_flow.py          # E2E test with retry
├── main.py               # CLI entry point
├── Dockerfile            # python:3.14-slim + uv
├── render.yaml           # Render blueprint
├── pyproject.toml
├── .env.example
└── .gitignore
```

## Setup

```bash
git clone <repo-url>
cd pr-autogen-agent
uv sync
cp .env.example .env
# Edit .env: GROQ_API_KEY, GITHUB_TOKEN, GITHUB_APP_ID, GITHUB_PRIVATE_KEY, GITHUB_WEBHOOK_SECRET
```

## Usage

```bash
# CLI: pass issue as argument
uv run python main.py "The add function returns wrong results, fix it"

# CLI: pipe issue from file
uv run python main.py < issue.txt

# Server
uv run python -m uvicorn server.app:app --port 8000
```

## Tech Stack

| Component | Technology |
|---|---|
| **Agent Framework** | AutoGen 0.7.x (`autogen-agentchat`) |
| **LLM Provider** | Groq (`llama-3.3-70b-versatile`) |
| **Model Client** | `OpenAIChatCompletionClient` |
| **Orchestration** | 3-agent linear `SequentialFlow` |
| **Git Integration** | `FunctionTool` wrappers via subprocess |
| **Server** | FastAPI + uvicorn |
| **Deployment** | Docker → Render (free tier) |
| **Auth** | GitHub App JWT + installation tokens |
| **Secrets** | `.env` (ignored by git) |
| **Python** | 3.14 |
| **Package Manager** | `uv` |

## Phases

| Phase | Status | Description |
|---|---|---|
| **1. Core flow** | ✅ Done | 3-agent linear workflow, `fix_and_create_pr` tool, CLI entry point |
| **2. Server** | ✅ Done | FastAPI app, auth, webhook, clone/cleanup, runner |
| **3. Deploy** | ⏳ Ready | Dockerfile + render.yaml done, needs GitHub App creation + deploy |
| **4. Production** | ⏳ Pending | Error commenting on issues, BYOK, monitoring |
