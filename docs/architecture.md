# AI PR Agent — Architecture Document

## Overview

An AutoGen-powered multi-agent system that takes a Jira issue or plain text description, explores the codebase, implements a fix, creates a PR, and iterates on human feedback.

---

## High-Level Flow

```
User Input (text: issue description)
        │
        ▼
┌──────────────── GraphFlow (DAG) ──────────────────────┐
│                                                       │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐         │
│  │ Explorer │──▶│ Planner  │──▶│  Fixer   │         │
│  │ Agent    │   │ Agent    │   │  Agent   │         │
│  └──────────┘   └──────────┘   └────┬─────┘         │
│                                      │               │
│  ┌──────────┐               ┌───────▼──────┐        │
│  │ PR       │◀──────────────│  Reviewer    │        │
│  │ Creator  │               │  Agent       │        │
│  └──────────┘               └──────────────┘        │
│                                     │                │
│                            needs fix │ approved      │
│                                     ▼                │
│                            ┌─────────────────┐      │
│                            │  PR Created     │      │
│                            │  (awaits review)│      │
│                            └────────┬────────┘      │
└─────────────────────────────────────┼────────────────┘
                                      │
                        ┌─────────────▼─────────────┐
                        │  Human Review             │
                        │  (approve or comment)     │
                        └─────────────┬─────────────┘
                                      │
                          ┌───────────▼───────────┐
                          │  Approve?             │
                          └───┬───────────────┬───┘
                         yes │               │ no
                             ▼               ▼
                      ┌──────────┐  ┌──────────────────┐
                      │ Merge PR │  │ Feedback Loop     │
                      └──────────┘  │ Agent parses      │
                                    │ comments, re-     │
                                    │ fixes, pushes     │
                                    │ new commits       │
                                    └──────────────────┘
                                             │
                                             ▼
                                      ┌──────────────┐
                                      │ Updated PR   │
                                      │ (re-review)  │
                                      └──────────────┘
```

---

## Agent Definitions

### 1. Explorer Agent

| Field | Value |
|---|---|
| **Goal** | Understand the codebase and locate files relevant to the issue |
| **Model** | Groq Llama 3.3 70B (or stronger for complex repos) |
| **Tools** | `read_file`, `grep_search`, `list_directory` |
| **System Prompt** | _"You are a codebase explorer. Given an issue description, find the relevant files and understand how they work. Summarize your findings concisely. Focus only on files directly related to the bug or feature."_ |
| **Output** | Summary of findings: which files are relevant, what they do, and what needs to change |

### 2. Planner Agent

| Field | Value |
|---|---|
| **Goal** | Create a concrete, step-by-step fix plan based on exploration |
| **Model** | Groq Llama 3.3 70B |
| **Tools** | None (pure LLM reasoning) |
| **System Prompt** | _"You are a senior software engineer. Based on the exploration findings, create a detailed step-by-step plan to fix the issue. Each step should specify the file and the exact change needed."_ |
| **Output** | Structured fix plan with file paths and change descriptions |

### 3. Fixer Agent

| Field | Value |
|---|---|
| **Goal** | Implement the fix by editing files |
| **Model** | Groq Llama 3.3 70B |
| **Tools** | `write_file`, `edit_file` (via `CodeExecutorAgent` or custom `FunctionTool`) |
| **System Prompt** | _"You are an implementer. Follow the plan and apply the changes. Output the exact file contents or diffs needed. After changes, run linting tools to verify."_ |
| **Output** | Applied code changes |

### 4. Reviewer Agent

| Field | Value |
|---|---|
| **Goal** | Review the diff for correctness, edge cases, and style |
| **Model** | Groq Llama 3.3 70B |
| **Tools** | `read_diff`, `run_linter` |
| **System Prompt** | _"You are a senior code reviewer. Review the changes. Check for: correctness, missing edge cases, code style, breaking changes, and test coverage. If everything looks good, end your response with 'APPROVED'. Otherwise, explain what needs to be fixed."_ |
| **Output** | Review verdict: APPROVED or fix requests |
| **Termination** | `TextMentionTermination("APPROVED")` |

### 5. PR Creator Agent

| Field | Value |
|---|---|
| **Goal** | Create a git branch, commit changes, push, and open a PR |
| **Model** | Groq Llama 3.3 70B |
| **Tools** | `CodeExecutorAgent` (for `git checkout -b`, `git add`, `git commit`, `git push`, `gh pr create`) |
| **System Prompt** | _"You create pull requests. Create a new branch, commit the reviewed changes, push to origin, and open a PR with a clear title and description referencing the issue."_ |
| **Output** | GitHub PR URL |

### 6. Feedback Handler Agent

| Field | Value |
|---|---|
| **Goal** | Parse human review comments and apply fixes |
| **Model** | Groq Llama 3.3 70B |
| **Tools** | `read_file`, `edit_file`, `gh_pr_comment` |
| **System Prompt** | _"You handle PR review feedback. Parse each comment, identify the file and line, understand the requested change, and apply it."_ |
| **Output** | Updated code with new commit pushed to the same PR branch |

---

## Team / Orchestration

### Primary Workflow: `GraphFlow`

```python
graph = DiGraph()
graph.add_edge("explorer", "planner")
graph.add_edge("planner", "fixer")
graph.add_edge("fixer", "reviewer")

# If reviewer says APPROVED → PR Creator
# If reviewer says fix needed → back to fixer
graph.add_edge("reviewer", "pr_creator")   # APPROVED path
graph.add_edge("reviewer", "fixer")        # needs fix path

team = GraphFlow(participants=[explorer, planner, fixer, reviewer, pr_creator], graph=graph)
```

### Feedback Loop: Manual Trigger

When you submit a review, either via webhook or CLI:

```python
feedback_team = RoundRobinGroupChat(
    [feedback_handler, fixer, reviewer, pr_updater],
    termination_condition=TextMentionTermination("APPROVED"),
    max_turns=5,  # prevent infinite loops
)
await feedback_team.run(task=f"Review comments: {comments_text}")
```

---

## Trigger Options for Feedback Loop

### Option A: Webhook (Recommended for MVP)

GitHub sends a webhook when a PR review is submitted → FastAPI server triggers the feedback agent.

```
GitHub PR Review → Webhook → FastAPI → AutoGen Feedback Agent → New Commit
```

Use **ngrok** for local development:
```bash
ngrok http 8000
```

Configure GitHub repo → Settings → Webhooks → Payload URL: `https://your-ngrok-url.ngrok.dev/webhook/github`

### Option B: GitHub Actions

```yaml
# .github/workflows/pr-feedback.yml
on:
  pull_request_review:
    types: [submitted]

jobs:
  process:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python process_feedback.py
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          PR_NUMBER: ${{ github.event.pull_request.number }}
```

### Option C: Polling

```python
while True:
    comments = get_pr_comments(repo, pr_number)
    if comments and comments != last_processed:
        await process_feedback(comments)
    await asyncio.sleep(60)
```

---

## Tool Implementations

### File Tools (`tools/file_tools.py`)

| Tool | Description |
|---|---|
| `read_file(path: str) -> str` | Read a file from the local filesystem |
| `write_file(path: str, content: str) -> str` | Overwrite a file |
| `edit_file(path: str, old_str: str, new_str: str) -> str` | Find and replace in a file |
| `grep_search(pattern: str, path: str) -> list` | Search for a pattern in files |
| `list_directory(path: str) -> list` | List files in a directory |

All implemented as `FunctionTool` wrappers.

### Git Tools (`tools/git_tools.py`)

Leverage `CodeExecutorAgent` to run:

| Command | Purpose |
|---|---|
| `git checkout -b fix/issue-123` | Create a new branch |
| `git add <files>` | Stage changes |
| `git commit -m "Fix: ..."` | Commit |
| `git push origin fix/issue-123` | Push branch |
| `gh pr create --title "..." --body "..."` | Create PR |
| `gh pr comment <pr> --body "..."` | Add PR comment |

---

## Safety Guardrails

| Guardrail | Implementation |
|---|---|
| **Never push to main** | Fixer always creates a new branch |
| **Approval gate** | PR Creator asks for user confirmation before pushing |
| **Max iterations** | `MaxMessageTermination(10)` on feedback loop |
| **Lint before commit** | Reviewer runs linter, Fixer only commits if lint passes |
| **User approval for push** | `UserProxyAgent` as a gate before `git push` |

---

## Tech Stack

| Component | Technology |
|---|---|
| **Agent Framework** | AutoGen 0.7.x (`autogen-agentchat`) |
| **LLM Provider** | Groq (Llama 3.3 70B via OpenAI-compatible API) |
| **Code Execution** | `LocalCommandLineCodeExecutor` |
| **Orchestration** | `GraphFlow` with `DiGraph` |
| **Git Integration** | `gh` CLI via `CodeExecutorAgent` |
| **Feedback Webhook** | FastAPI + ngrok (dev) |
| **Secrets** | `.env` file (GROQ_API_KEY, GITHUB_TOKEN) |

---

## Project Structure

```
autogen-pr-agent/
├── agents/
│   ├── __init__.py
│   ├── explorer.py
│   ├── planner.py
│   ├── fixer.py
│   ├── reviewer.py
│   ├── pr_creator.py
│   └── feedback_handler.py
├── tools/
│   ├── __init__.py
│   ├── file_tools.py
│   └── git_tools.py
├── server/
│   ├── __init__.py
│   └── webhook.py            # FastAPI webhook server
├── workflow.py                # GraphFlow definition
├── main.py                    # Entry point
├── .env                       # Secrets
├── pyproject.toml
└── README.md
```

---

## Phase Plan

### Phase 1: MVP (Manual Text Input)
- Hardcode issue text as input
- Explorer → Planner → Fixer → Reviewer → PR Creator
- Manual re-trigger for feedback loop

### Phase 2: Feedback Loop
- Add webhook server (FastAPI + ngrok)
- Feedback Handler agent parses review comments
- Agent pushes new commits to same PR

### Phase 3: Jira Integration
- `FunctionTool` wrapping Jira REST API
- Fetch issue details, ACs, and linked tickets

### Phase 4: Production Hardening
- Add authentication to webhook
- Persistent agent state / conversation memory
- Monitoring and logging
- Error recovery (retry on API failure)
