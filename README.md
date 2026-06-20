# pr-autogen-agent

An AutoGen-powered multi-agent system that takes an issue description, explores a codebase, fixes the code, creates a GitHub PR, and handles review feedback.

## Architecture

```
User Input (issue description)
        │
        ▼
┌──────────────── GraphFlow ──────────────────────┐
│                                                  │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐     │
│  │ Explorer │──►│ Planner  │──►│  Fixer   │     │
│  └──────────┘   └──────────┘   └────┬─────┘     │
│                                      │           │
│  ┌──────────┐               ┌───────▼──────┐    │
│  │ PR       │◀──────────────│  Reviewer    │    │
│  │ Creator  │               │  Agent       │    │
│  └──────────┘               └──────────────┘    │
│                                     │            │
│                            needs fix │ approved  │
│                                     ▼            │
│                            ┌─────────────────┐  │
│                            │  PR Created     │  │
│                            │  (awaits review)│  │
│                            └─────────────────┘  │
└──────────────────────────────────────────────────┘
```

Each agent receives the **full conversation history** from all previous agents. The `GraphFlow` runtime routes messages between agents based on conditional edges.

## Agents

| Agent | Tools | Purpose |
|---|---|---|
| **Explorer** | `list_directory`, `read_file`, `grep_search` | Scans the codebase to find files relevant to the issue |
| **Planner** | _(none — pure LLM)_ | Creates a step-by-step fix plan from exploration findings |
| **Fixer** | `read_file`, `write_file`, `edit_file` | Applies the planned changes to the codebase |
| **Reviewer** | `read_file` | Reads changed files and approves or requests fixes |
| **PR Creator** | `run_git`, `create_pr`, `setup_git_auth` | Creates a git branch, commits, pushes, and opens a GitHub PR |

## Workflow Graph

```python
# Defined in workflow.py
nodes = {
    "explorer": DiGraphNode(edges=["planner"]),
    "planner": DiGraphNode(edges=["fixer"]),
    "fixer": DiGraphNode(edges=["reviewer"]),
    "reviewer": DiGraphNode(
        edges=[
            DiGraphEdge(target="pr_creator", condition="APPROVED"),
            DiGraphEdge(target="fixer", condition=needs_fix, activation_group="backward"),
        ],
    ),
    "pr_creator": DiGraphNode(edges=[]),
}
```

**Routing logic:**
- Forward: `explorer → planner → fixer → reviewer`
- If reviewer's response contains `"APPROVED"` → `pr_creator`
- If reviewer's response does NOT contain `"APPROVED"` → `fixer` (loop with `activation_group="backward"`)

**Termination:** `TextMentionTermination("PR_CREATED") | MaxMessageTermination(20)`

## How Agents Communicate

1. When an agent finishes, its final text response is published to the message bus
2. `GraphFlow` evaluates edge conditions on that message to determine the next agent
3. The next agent receives the **entire conversation history** (all previous agents' messages)
4. Each agent can make **multiple consecutive tool calls** within its turn
5. Tool results are fed back to the LLM, which decides whether to continue calling tools or respond

### Agent Internal Loop (per agent turn)

```
LLM receives full history + system prompt + tools
        │
        ▼
LLM returns FunctionCalls (e.g. read_file, edit_file)
        │
        ▼
AutoGen executes each FunctionTool locally
        │
        ▼
FunctionExecutionResults are sent back to LLM
        │
        ▼
LLM returns text response (or more tool calls)
        │
        ▼
Text response is published → GraphFlow routes to next agent
```

## Message Flow

```
┌──────────┐    text     ┌──────────┐    text     ┌──────────┐
│ Explorer │──────────►│ Planner │──────────►│  Fixer  │
└──────────┘           └──────────┘           └────┬─────┘
                                                   │
                                              text │
                                                   ▼
                                            ┌──────────┐
                                            │ Reviewer │
                                            └────┬─────┘
                                                 │
                                   ┌─────────────┴─────────────┐
                                   │ text                      │ text
                                   │ "APPROVED"                │ no "APPROVED"
                                   ▼                           ▼
                            ┌──────────┐              ┌──────────┐
                            │PR Creator│              │  Fixer   │
                            └──────────┘              └──────────┘
                                   │
                                   ▼
                            "PR_CREATED"
                            → workflow terminates
```

## Tech Stack

| Component | Technology |
|---|---|
| **Agent Framework** | AutoGen 0.7.x (`autogen-agentchat`) |
| **LLM Provider** | OpenRouter / Groq (OpenAI-compatible API) |
| **Model Client** | Custom `RawGroqClient` (bypasses AutoGen's tool processing issues) |
| **Code Execution** | `LocalCommandLineCodeExecutor` |
| **Orchestration** | `GraphFlow` with `DiGraph` (directed graph) |
| **Git Integration** | `subprocess` via `FunctionTool` wrappers |
| **Secrets** | `.env` file (`OPEN_ROUTER_API_KEY`, `GROQ_API_KEY`, `GITHUB_TOKEN`) |
| **Python** | 3.14 |
| **Package Manager** | `uv` |

## Why `RawGroqClient`?

AutoGen's built-in `OpenAIChatCompletionClient` sends `strict: false` and `additionalProperties: false` in tool schemas. This triggers Groq's Llama model to switch to a malformed XML tool call format (`<function=name{...}` without closing `>`). The `RawGroqClient` in `config.py` bypasses this by:

1. Using the raw `AsyncOpenAI` client directly (same API format)
2. Stripping problematic fields from tool schemas (`strict`, `additionalProperties`)
3. Post-processing XML-style `<function=name>args</function>` responses from the model
4. Properly handling `tool_choice` for reflection and non-reflection modes

## Project Structure

```
pr-autogen-agent/
├── agents/
│   ├── __init__.py
│   ├── explorer.py          # Scans codebase for relevant files
│   ├── planner.py           # Creates fix plan (no tools)
│   ├── fixer.py             # Applies code changes
│   ├── reviewer.py          # Reviews changes, approves or requests fixes
│   └── pr_creator.py        # Creates git branch + GitHub PR
├── tools/
│   ├── __init__.py
│   ├── file_tools.py        # read_file, write_file, edit_file, grep_search, list_directory
│   └── git_tools.py         # run_git, create_pr, setup_git_auth, get_pr_comments
├── server/
│   ├── __init__.py
│   └── webhook.py           # FastAPI webhook (for feedback loop)
├── docs/
│   ├── architecture.md      # Detailed architecture documentation
│   ├── agent-communication.md  # Agent communication & message flow
│   └── implementation-plan.md  # Implementation plan & phases
├── config.py                # RawGroqClient model client + message converters
├── workflow.py              # GraphFlow definition with DiGraph
├── test_flow.py             # E2E test with retry logic
├── main.py                  # Entry point
├── pyproject.toml           # Project metadata & dependencies
├── .env.example             # Environment variable template
└── .gitignore
```

## Setup

```bash
# Clone and install
git clone <repo-url>
cd pr-autogen-agent
uv sync

# Configure environment
cp .env.example .env
# Edit .env with your API keys:
#   OPEN_ROUTER_API_KEY=sk-or-v1-...
#   GITHUB_TOKEN=ghp_...
```

## Usage

```bash
# Run the test flow against the test repo
uv run python test_flow.py

# Run with a custom issue (once main.py is implemented)
uv run python main.py "The add function returns wrong results..."
```

## E2E Test

`test_flow.py` runs the full agent pipeline against a test repository at `/private/var/folders/jd/bm1_qs2d6qng6brmj0b44s8c0000gn/T/opencode/test-repo`.

Features:
- Resets the test repo to a known state before each run
- Retries up to 3 times on transient errors (rate limits, etc.)
- Prints each agent's tool calls and responses

## Phases

| Phase | Status | Description |
|---|---|---|
| **1. MVP** | ✅ Complete | Explorer → Planner → Fixer → Reviewer → PR Creator (manual text input) |
| **2. Feedback Loop** | ⏳ Pending | Webhook server + Feedback Handler agent for PR review iterations |
| **3. Jira Integration** | ⏳ Pending | FunctionTool wrappers for Jira REST API |
| **4. Production** | ⏳ Pending | Auth, monitoring, error recovery, persistent state |
