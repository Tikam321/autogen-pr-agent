# AI PR Agent — Implementation Plan

## Phase 1: MVP (Manual Text Input)

### Step 1: Project Scaffold

Create the folder structure and initialize dependencies.

**Files to create:**
- `ai-pr-agent/pyproject.toml` — project config with autogen-agentchat, autogen-ext[openai], dotenv, fastapi, uvicorn
- `ai-pr-agent/.env.example` — template for GROQ_API_KEY, GITHUB_TOKEN
- `ai-pr-agent/.gitignore` — .venv, .env, __pycache__
- `ai-pr-agent/agents/__init__.py`
- `ai-pr-agent/tools/__init__.py`
- `ai-pr-agent/server/__init__.py`

**Commands:**
```bash
uv init ai-pr-agent
uv add autogen-agentchat autogen-ext[openai] python-dotenv
```

### Step 2: File Tools — `tools/file_tools.py`

Implement `FunctionTool` wrappers for filesystem operations.

| Function | Tool Name | Description |
|---|---|---|
| `read_file(path: str) -> str` | `read_file` | Read a file from disk |
| `write_file(path: str, content: str) -> str` | `write_file` | Overwrite a file |
| `edit_file(path: str, old_string: str, new_string: str) -> str` | `edit_file` | Find-and-replace in a file |
| `grep_search(pattern: str, path: str) -> list` | `grep_search` | Regex search in files |
| `list_directory(path: str) -> list` | `list_directory` | List files in a directory |

All wrapped via `FunctionTool(func, description=...)` and exported as a list.

```python
# Pattern:
from autogen_core.tools import FunctionTool

def read_file(path: str) -> str: ...

read_file_tool = FunctionTool(read_file, description="Read a file from the local filesystem")

file_tools = [read_file_tool, write_file_tool, edit_file_tool, grep_search_tool, list_directory_tool]
```

### Step 3: Git Tools — `tools/git_tools.py`

Create a `CodeExecutorAgent` for executing git and gh commands.

The agent gets a `LocalCommandLineCodeExecutor` that runs in the repo directory.

**Commands the agent will use:**
```
git checkout -b fix/<issue-ref>
git add <files>
git commit -m "fix: <description>"
git push origin fix/<issue-ref>
gh pr create --title "<title>" --body "<body>"
gh pr comment <pr-number> --body "<comment>"
```

```python
from autogen_ext.code_executors.local import LocalCommandLineCodeExecutor
from autogen_agentchat.agents import CodeExecutorAgent

executor = LocalCommandLineCodeExecutor(work_dir="/path/to/target/repo")
git_agent = CodeExecutorAgent("git_executor", code_executor=executor)
```

### Step 4: Explorer Agent — `agents/explorer.py`

**Goal:** Understand the codebase and locate files relevant to the issue.

| Field | Value |
|---|---|
| **Class** | `AssistantAgent` |
| **Name** | `explorer` |
| **Tools** | `read_file`, `grep_search`, `list_directory` |
| **System Message** | _"You are a codebase explorer. Given an issue description, find the relevant files and understand how they work. Summarize your findings concisely. Focus only on files directly related to the bug or feature."_ |

**Implementation:**
```python
from autogen_agentchat.agents import AssistantAgent

explorer = AssistantAgent(
    "explorer",
    model_client=model_client,
    tools=file_tools,
    system_message="You are a codebase explorer...",
)
```

### Step 5: Planner Agent — `agents/planner.py`

**Goal:** Create a concrete, step-by-step fix plan.

| Field | Value |
|---|---|
| **Class** | `AssistantAgent` |
| **Name** | `planner` |
| **Tools** | None (pure LLM reasoning) |
| **System Message** | _"You are a senior software engineer. Based on the exploration findings, create a detailed step-by-step plan to fix the issue. Each step should specify the file and the exact change needed."_ |

### Step 6: Fixer Agent — `agents/fixer.py`

**Goal:** Implement the fix by editing files.

| Field | Value |
|---|---|
| **Class** | `AssistantAgent` |
| **Name** | `fixer` |
| **Tools** | `read_file`, `write_file`, `edit_file` |
| **System Message** | _"You are an implementer. Follow the plan and apply the changes. Output the exact file contents or diffs needed."_ |

### Step 7: Reviewer Agent — `agents/reviewer.py`

**Goal:** Review the diff for correctness, edge cases, and style.

| Field | Value |
|---|---|
| **Class** | `AssistantAgent` |
| **Name** | `reviewer` |
| **Tools** | `read_file` |
| **System Message** | _"You are a senior code reviewer. Review the changes for correctness, missing edge cases, code style, breaking changes, and test coverage. If everything looks good, end your response with 'APPROVED'. Otherwise, explain what needs to be fixed."_ |
| **Termination** | `TextMentionTermination("APPROVED")` |

### Step 8: PR Creator Agent — `agents/pr_creator.py`

**Goal:** Create branch, commit, push, and open a PR.

| Field | Value |
|---|---|
| **Class** | `AssistantAgent` |
| **Name** | `pr_creator` |
| **Tools** | `CodeExecutorAgent` (git/gh commands) |
| **System Message** | _"You create pull requests. Create a new branch, commit the reviewed changes, push to origin, and open a PR with a clear title and description referencing the issue."_ |

### Step 9: Workflow — `workflow.py`

Define the `GraphFlow` that orchestrates all agents.

```python
from autogen_agentchat.teams import GraphFlow
from autogen_agentchat.graph import DiGraph

graph = DiGraph()
graph.add_edge("explorer", "planner")
graph.add_edge("planner", "fixer")
graph.add_edge("fixer", "reviewer")
graph.add_edge("reviewer", "pr_creator")   # APPROVED path
graph.add_edge("reviewer", "fixer")        # needs-fix path (loop)

team = GraphFlow(
    participants=[explorer, planner, fixer, reviewer, pr_creator],
    graph=graph,
    termination_condition=TextMentionTermination("APPROVED"),
)
```

**Flow logic:**
1. Explorer investigates the repo → outputs findings
2. Planner creates a fix plan → outputs step-by-step plan
3. Fixer applies the changes → outputs modified files
4. Reviewer checks the diff → outputs "APPROVED" or fix requests
5. If approved → PR Creator branches, commits, pushes, creates PR
6. If not approved → loop back to Fixer (up to `max_turns` limit)

### Step 10: Entry Point — `main.py`

```python
import asyncio
from dotenv import load_dotenv

load_dotenv()

async def main():
    issue_description = input("Paste the issue description: ")
    
    result = await team.run(task=issue_description)
    print("Final result:", result.messages[-1].content)

asyncio.run(main())
```

**CLI usage:**
```bash
cd ai-pr-agent
uv run python main.py
# Paste: "The login button throws 500 error when email is empty"
```

### Step 11: Test End-to-End

1. Run `main.py` with a known issue in a test repo
2. Verify Explorer finds relevant files
3. Verify Planner creates a logical fix plan
4. Verify Fixer applies the changes correctly
5. Verify Reviewer approves (or loops back)
6. Verify PR is created on GitHub
7. Manually verify the PR diff is correct

---

## Phase 2: Feedback Loop

### Step 12: Feedback Handler Agent — `agents/feedback_handler.py`

| Field | Value |
|---|---|
| **Class** | `AssistantAgent` |
| **Name** | `feedback_handler` |
| **Tools** | `read_file`, `write_file`, `edit_file`, `gh_pr_comment` |
| **System Message** | _"You handle PR review feedback. Parse each comment, identify the file and line, understand the requested change, and apply it."_ |

### Step 13: Webhook Server — `server/webhook.py`

FastAPI server that listens for GitHub PR review events.

```python
from fastapi import FastAPI, Request

app = FastAPI()

@app.post("/webhook/github")
async def github_webhook(request: Request):
    payload = await request.json()
    if payload.get("action") in ["submitted", "created"]:
        asyncio.create_task(process_feedback(payload))
    return {"ok": True}
```

**Dev setup:** `ngrok http 8000` → configure GitHub webhook URL.

### Step 14: Wire Feedback Loop

When webhook fires:
1. Parse PR number, comments from payload
2. Run `RoundRobinGroupChat([feedback_handler, fixer, reviewer, pr_updater])`
3. Fixer applies changes → new commit pushed to same PR branch

---

## Phase 3: Jira Integration

### Step 15: Jira Tool — `tools/jira_tools.py`

`FunctionTool` wrapping Jira REST API.

| Function | Description |
|---|---|
| `fetch_issue(issue_key: str) -> dict` | Get issue details, description, ACs |
| `transition_issue(issue_key: str, status: str) -> bool` | Update issue status |
| `add_comment(issue_key: str, comment: str) -> bool` | Add comment to issue |

### Step 16: Wire Jira → Agent

Replace manual text input with `fetch_issue(issue_key)` at the start of the workflow.

---

## Phase 4: Production Hardening

- Add authentication to webhook (verify GitHub signature)
- Persistent agent state / conversation memory
- Monitoring and logging (structured logging, metrics)
- Error recovery (retry on API failure, circuit breaker)
- Concurrent PR handling (queue system)
- Rate limiting for API calls

---

## Effort Estimate

| Phase | Steps | Est. Effort |
|---|---|---|
| Phase 1 (MVP) | Steps 1-11 | 3-4 days |
| Phase 2 (Feedback) | Steps 12-14 | 2-3 days |
| Phase 3 (Jira) | Steps 15-16 | 1-2 days |
| Phase 4 (Hardening) | Step 17 | 2-3 days |
| **Total** | **17 steps** | **8-12 days** |

---

## Implementation Order

```
Phase 1 ──────────────────────────────────────────────────
Step 1: Scaffold (pyproject.toml, folders, .env)
    │
    ├──▶ Step 2: File tools        ───┐
    ├──▶ Step 3: Git tools         ───┤  parallel
    └──▶ Steps 4-8: Agents         ───┘
              │
              ▼
         Step 9: Workflow (GraphFlow)
              │
              ▼
         Step 10: Entry point (main.py)
              │
              ▼
         Step 11: Test

Phase 2 ──────────────────────────────────────────────────
Step 12: Feedback Handler
Step 13: Webhook server
Step 14: Wire loop

Phase 3 ──────────────────────────────────────────────────
Step 15: Jira tools
Step 16: Wire Jira → Agent

Phase 4 ──────────────────────────────────────────────────
Step 17: Production hardening
```

---

## Verification Checklist (Per Step)

- [ ] **Step 1:** `uv run python -c "from autogen_agentchat.agents import AssistantAgent"` works
- [ ] **Step 2:** Each file tool function returns correct output
- [ ] **Step 3:** Git agent can run `git status`, `gh --version`
- [ ] **Step 4:** Explorer agent reads files and summarizes
- [ ] **Step 5:** Planner agent outputs a structured plan
- [ ] **Step 6:** Fixer agent applies changes to files
- [ ] **Step 7:** Reviewer agent outputs APPROVED or fix requests
- [ ] **Step 8:** PR Creator creates branch, commits, pushes, opens PR
- [ ] **Step 9:** GraphFlow runs agents in correct order
- [ ] **Step 10:** `uv run python main.py` works end-to-end
- [ ] **Step 11:** PR is created on GitHub with correct changes
