# Agent Communication & Message Flow

## How AutoGen Agents Talk To Each Other

AutoGen's `GraphFlow` uses a **sequential message-passing bus** — there is no direct agent-to-agent method call. Everything goes through the graph runtime.

### Core Mechanism

1. **Each agent is an `AssistantAgent`** wrapping a model client (`RawGroqClient`).
2. **Agents are stateless** — they hold no memory between invocations.
3. **Full conversation history** is passed to each agent when it's its turn.
4. **Output of one agent = input context for all downstream agents.**

### The Graph (from `workflow.py`)

```
User Input
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  explorer ──► planner ──► fixer ──► reviewer        │
│                                      │              │
│                          ┌───────────┴───────────┐  │
│                     APPROVED              needs_fix│  │
│                          │                   │    │  │
│                          ▼                   ▼    │  │
│                     pr_creator              fixer │  │
│                          │                   │    │  │
│                          ▼                   └────┘  │
│                     PR_CREATED                       │
└─────────────────────────────────────────────────────┘
```

**Termination**: `TextMentionTermination("PR_CREATED") | MaxMessageTermination(20)`

The `|` operator means: stop when either condition is met.

### Edge Conditions

```python
reviewer: DiGraphNode(
    edges=[
        DiGraphEdge(target="pr_creator", condition="APPROVED"),   # String match
        DiGraphEdge(target="fixer", condition=needs_fix, activation_group="backward"),  # Function
    ],
)
```

- `condition="APPROVED"` — routes to `pr_creator` if `message.to_model_text()` contains "APPROVED"
- `condition=needs_fix` — routes to `fixer` if `"APPROVED" not in message.to_model_text()`

Only **one** edge fires per agent turn (the first matching condition is used).

### Activation Groups

The **fixer** has two incoming edges:
- `planner → fixer` with `activation_group="forward"`
- `reviewer → fixer` (in `needs_fix` path) with `activation_group="backward"`

This prevents the fixer from being activated twice when both input paths are satisfied. Only one activation group fires per cycle.

## Agent Internal Loop

When an agent is activated, it runs this loop internally:

```
LLM receives messages (history + system prompt + tools)
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
LLM reflects (if reflect_on_tool_use=True)
        │
        ▼
LLM returns final text response
        │
        ▼
That text is published as the agent's output message
```

**Key detail**: The `RawGroqClient` sits between AutoGen and the LLM API. It converts AutoGen's internal message types to OpenAI-compatible API format, and converts API responses back to AutoGen types.

## Message Types In Transit

| AutoGen Type | When It's Created | What It Contains |
|---|---|---|
| `TextMessage` | Agent's final text response | The agent's output, passed to next node |
| `ToolCallRequestEvent` | LLM returns tool_calls | Function name + JSON arguments |
| `ToolCallExecutionEvent` | After tool runs | Tool return value or error |
| `ToolCallSummaryMessage` | After all tools run | Summary of results |
| `TaskResult` | Workflow terminates | All messages from the run |

## Step-By-Step Flow With Real Data

Below is sample output from an actual run, annotated to show what happens at each step.

---

### 1. User Input → Explorer

**What AutoGen sends to the LLM**:
```
system: You are a codebase explorer. Given an issue description, do the following:
         1. First, call list_directory on './' to see what files exist.
         2. For each relevant file found, call read_file to get its contents.
         3. If you need to find specific patterns, use grep_search.
         4. Summarize your findings concisely...

user: The add function in calculator.py returns wrong results...
      When I call add(2, 3), it returns -1 instead of 5...
```

**LLM response** (3 parallel function calls):
```json
{
  "tool_calls": [
    {"name": "list_directory", "arguments": "{\"path\":\"./\"}"},
    {"name": "read_file", "arguments": "{\"path\":\"./calculator.py\"}"},
    {"name": "grep_search", "arguments": "{\"pattern\":\"def add\", \"path\":\"./\"}"}
  ]
}
```

**AutoGen executes each tool**:
```
list_directory("./") → ['.git/', '.gitignore', 'calculator.py', 'main.py', ...]
read_file("./calculator.py") → "def add(a: int, b: int) -> int:\n    return a - b\n..."
grep_search("def add", "./") → ["calculator.py:1: def add(a: int, b: int) -> int:"]
```

**LLM sees results and reflects** (with `reflect_on_tool_use=True`):
```
tool results are fed back to LLM
LLM generates text response (no more tool calls needed)
```

**Explorer's output message** (this is what gets passed to the next node):
```
The issue is in the `add` function in `calculator.py`.
The function is currently subtracting `b` from `a` instead of adding them together.
To fix this, change `return a - b` to `return a + b`.
```

Since the explorer has only one edge (`→ planner`), this text is routed directly to the planner.

---

### 2. Explorer → Planner

**What AutoGen sends to the LLM**:
```
system: You are a senior software engineer. Based on the exploration findings below,
        create a detailed step-by-step plan to fix the issue...

user: The add function in calculator.py returns wrong results...

assistant (explorer): The issue is in the `add` function in `calculator.py`.
                      The function is currently subtracting...
```

**Planner's output message** (no tools available — pure text):
```
To fix the issue with the `add` function in `calculator.py`, follow these steps:

1. Open the file `calculator.py`.
2. Locate the `add` function definition.
3. Change the line `return a - b` to `return a + b` in the `add` function.
```

The planner has one edge (`→ fixer`). This text is passed to the fixer.

---

### 3. Planner → Fixer

**What AutoGen sends to the LLM** (full history + fixer's system prompt):
```
user: The add function...
assistant (explorer): ...summary...
assistant (planner): ...step-by-step plan...
system: (fixer's system prompt) You are an implementer...
```

**Fixer's tool calls**:
```
1. read_file({"path": "calculator.py"})  → gets current content
2. edit_file({"path": "calculator.py",
              "old_string": "return a - b",
              "new_string": "return a + b"})
```

After reflection, the fixer's output:
```
The fix has been applied. Changed `return a - b` to `return a + b` in `calculator.py`.
```

Edge: `fixer → reviewer` (unconditional). Passed to reviewer.

---

### 4. Fixer → Reviewer

**Reviewer reads the file**:
```
read_file({"path": "calculator.py"}) → confirms the edit was applied
```

**Reviewer's output** (two possible paths):

**Path A — APPROVED**:
```
I've reviewed the changes. The add function now correctly uses `+` instead of `-`.
Edge cases are handled. The fix is correct. APPROVED
```
➡ Contains "APPROVED" → routes to `pr_creator`

**Path B — needs fix**:
```
The code still has `return a - b`. The fix was not applied correctly.
Please change line 3 from `return a - b` to `return a + b`.
```
➡ Does NOT contain "APPROVED" → `needs_fix()` returns True → routes to `fixer` (loop)

---

### 5. Reviewer → PR Creator (APPROVED path)

**PR Creator's tool calls** (sequential via `run_git`):
```
1. setup_git_auth({"repo_dir": "."})          → injects GITHUB_TOKEN
2. run_git({"args": "checkout -b fix/add-function-bug"})
3. run_git({"args": "add calculator.py test_calculator.py"})
4. run_git({"args": "commit -m \"Fix add function bug: use + instead of -\""})
5. run_git({"args": "push origin fix/add-function-bug"})
6. create_pr({"owner": "Tikam321", "repo": "test-calculator", ...})
```

**PR Creator's output**:
```
PR #2 created at: https://github.com/Tikam321/test-calculator/pull/2
PR_CREATED
```

**Termination check**: `PR_CREATED` matches `TextMentionTermination("PR_CREATED")` → workflow stops.

---

### 5-alt. Reviewer → Fixer (needs fix — loop)

When the reviewer rejects, the fixer gets activated again with `activation_group="backward"`:

**What AutoGen sends to the LLM**:
```
user: The add function...
explorer: ...
planner: ...
fixer (1st attempt): ... (read file, attempted edit)
reviewer: The fix was not applied correctly. Please change...
```

**Fixer re-reads and re-edits**, then passes again to reviewer. This loop continues until either:
- Reviewer says APPROVED → PR Creator
- `MaxMessageTermination(20)` fires → workflow stops (safety limit)

## Conditional Edge Logic in Detail

```python
def needs_fix(message: BaseChatMessage) -> bool:
    return "APPROVED" not in message.to_model_text()
```

The `DiGraph` evaluates edges in order:
1. Check edge 1: `condition="APPROVED"` → if `"APPROVED"` in message text, route there
2. If not, check edge 2: `condition=needs_fix` → call function with message, if True, route there

The `BaseChatMessage` passed to the condition is the **last published message** from the current agent — typically a `TextMessage` containing the agent's final text response.

## Summary

```
┌──────────┐    text     ┌──────────┐    text     ┌──────────┐
│ Explorer │──────────►│ Planner │──────────►│  Fixer  │
└──────────┘           └──────────┘           └────┬─────┘
                                                   │
                                              text │ (file edited)
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
                            │PR Creator│              │  Fixer   │ (loop)
                            └──────────┘              └──────────┘
                                   │
                                   ▼
                            "PR_CREATED"
                            → termination
```

- Each agent receives the **entire message history** (not just the previous agent's output)
- The graph runtime evaluates edge **conditions** against the agent's output message
- Only **one edge fires** per agent turn
- `TextMentionTermination` monitors every message for the stop phrase
- `reflect_on_tool_use=True` adds an extra LLM call between tool execution and final response
