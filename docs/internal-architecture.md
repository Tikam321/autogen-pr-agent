# Internal Architecture — PR Autogen Agent

## 1. System Overview

A GitHub App that listens for opened issues, autonomously analyzes the codebase, generates a fix plan, implements the fix, and creates a Pull Request — all without human intervention.

```
┌────────────────────────────────────────────────────────────────────┐
│                      PR Autogen Agent System                       │
│                                                                    │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐   │
│   │  GitHub   │───▶│ FastAPI  │───▶│  Agent   │───▶│  Target  │   │
│   │   Issue   │    │  Server  │    │ Workflow │    │   Repo   │   │
│   └──────────┘    └──────────┘    └──────────┘    └──────────┘   │
│         │               │               │               │         │
│    webhook POST    verify/auth   3 agents run    PR created       │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

### Two Execution Paths

| Path | Entry Point | Use Case |
|---|---|---|
| **CLI** | `python main.py "issue text"` | Development testing, debugging |
| **Webhook** | GitHub Issue → POST `/webhook` | Production (GitHub App) |

Both paths converge on the same 3-agent workflow in `workflow.py`.

---

## 2. Directory Layout (Current)

```
pr-autogen-agent/
├── config.py                 # RawGroqClient — custom LLM client
├── workflow.py               # 3-node DiGraph definition
├── main.py                   # CLI entry point
│
├── agents/
│   ├── explorer.py           # Reads codebase, finds relevant files
│   ├── planner.py            # Pure LLM — creates fix plan
│   └── executor.py           # Calls fix_and_create_pr tool
│
├── tools/
│   ├── file_tools.py         # read_file, write_file, edit_file, grep, list_directory
│   └── git_tools.py          # fix_and_create_pr, create_full_pr, create_pr, setup_git_auth
│
├── server/
│   ├── app.py                # FastAPI app factory
│   ├── auth.py               # JWT → installation token
│   ├── webhook.py            # HMAC verification + issue handler
│   ├── repo_manager.py       # Clone + cleanup + comment_on_issue
│   └── runner.py             # chdir + agent workflow runner
│
├── Dockerfile                # python:3.14-slim + uv
├── render.yaml               # Render free-tier blueprint
├── pyproject.toml            # uv-managed dependencies
├── .env                      # Secrets (ignored by git)
└── .env.example              # Template for new devs
```

---

## 3. Authentication Architecture (GitHub App)

### 3.1 The Problem

We need to clone a user's private repo, read files, commit changes, and create PRs — all on behalf of that user, without asking for their password or a personal access token.

### 3.2 GitHub App Authentication Flow

```
┌──────────┐         ┌──────────┐         ┌──────────┐
│  GitHub   │         │  Our     │         │  Target  │
│  App      │         │  Server  │         │  Repo    │
└────┬─────┘         └────┬─────┘         └────┬─────┘
     │                    │                    │
     │  1. User installs  │                    │
     │     app on repo    │                    │
     │◀───────────────────│                    │
     │                    │                    │
     │  2. Webhook fires  │                    │
     │    (issue opened)  │                    │
     │───────────────────▶│                    │
     │                    │                    │
     │  3. Server signs   │                    │
     │     JWT with       │                    │
     │     private key    │                    │
     │◀───────────────────│                    │
     │                    │                    │
     │  4. POST /app/     │                    │
     │     installations/ │                    │
     │     :id/access_    │                    │
     │     tokens         │                    │
     │───────────────────▶│                    │
     │                    │                    │
     │  5. Returns short- │                    │
     │     lived token    │                    │
     │◀───────────────────│                    │
     │                    │                    │
     │  6. git clone --   │                    │
     │     depth 1 using  │                    │
     │     token auth     │                    │
     │────────────────────────────────────────▶│
     │                    │                    │
     │  7. Read, commit,  │                    │
     │     push, create   │                    │
     │     PR using token │                    │
     │────────────────────────────────────────▶│
```

### 3.3 JWT Generation (`server/auth.py`)

```python
# Step 1: Create a JWT signed with the GitHub App's private key
def _get_jwt() -> str:
    now = int(time.time())
    payload = {
        "iat": now - 60,       # issued 60s ago (clock skew tolerance)
        "exp": now + 600,      # expires in 10 minutes
        "iss": APP_ID,         # GitHub App ID (from env: 4108243)
    }
    key = PRIVATE_KEY.replace("\\n", "\n")  # .env stores with literal \n
    return pyjwt.encode(payload, key, algorithm="RS256")
```

The private key is stored in `.env` as a single line with `\n` escape sequences:
```
GITHUB_PRIVATE_KEY=-----BEGIN RSA PRIVATE KEY-----\nMIIEpA...\n-----END RSA PRIVATE KEY-----
```

The `.replace("\\n", "\n")` converts these escapes into real newlines before passing to PyJWT.

### 3.4 Installation Token Exchange (`server/auth.py`)

```python
# Step 2: Exchange JWT for a repo-scoped token
def get_installation_token(installation_id: int) -> str:
    jwt = _get_jwt()
    req = urllib.request.Request(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        data=b"",
        headers={
            "Authorization": f"Bearer {jwt}",
            "Accept": "application/vnd.github+json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    return data["token"]  # Valid for 1 hour
```

### 3.5 Token Usage

The returned token is an `x-access-token` — it acts as both authentication and authorization for:
- `git clone https://x-access-token:TOKEN@github.com/owner/repo`
- `git push` (after injecting into the remote URL)
- GitHub API calls (POST `/repos/owner/repo/pulls`, POST `/repos/owner/repo/issues/123/comments`)
- All operations are scoped to the permissions granted during app install (Contents: read/write, Issues: read, Pull requests: read/write)

---

## 4. Webhook Server Architecture

### 4.1 Request Lifecycle

```
GitHub POST /webhook
        │
        ▼
┌────────────────────────┐
│  1. verify_signature() │  HMAC-SHA256 with WEBHOOK_SECRET
│  2. Parse event +      │  Check X-GitHub-Event: "issues"
│     payload            │  Check action: "opened"
│  3. Extract fields:    │  installation_id, clone_url,
│     owner, repo,       │  issue_number, title, body
│    issue_number        │
└────────┬───────────────┘
         │
         ▼
┌────────────────────────┐
│ asyncio.create_task(   │  Return 200 {"ok": True} immediately
│   process_issue(...))  │  Agent runs in background
└────────────────────────┘
         │
         ▼
┌────────────────────────┐
│  4. get_installation_  │  JWT → installation token (1 hour)
│     token()            │
│  5. clone_repo()       │  git clone --depth 1 with token
│  6. run_agent()        │  chdir → run 3 agents → extract PR URL
│  7. cleanup_repo()     │  Delete temp directory
└────────────────────────┘
         │
    Success? ──Yes──▶ Return PR URL
         │
        No
         │
         ▼
┌────────────────────────┐
│  8. comment_on_issue(  │  Post error message on the issue
│     "Agent failed...") │  So user knows something happened
└────────────────────────┘
```

### 4.2 Signature Verification

```python
def verify_signature(payload: bytes, signature_header: str) -> bool:
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)
```

GitHub signs every webhook payload with the shared secret. We compute the expected HMAC and compare using `compare_digest` (constant-time, prevents timing attacks).

### 4.3 Why `asyncio.create_task`?

GitHub expects a webhook response within 10 seconds. The agent workflow can take 30-60 seconds (3 LLM calls + git operations). By spawning a background task and returning `200` immediately, we prevent GitHub from retrying the webhook.

### 4.4 Error Commenting

If the agent workflow throws an exception or returns no PR URL, the server posts a comment on the issue:
> 🤖 **PR Autogen Agent failed**
> ```
> RuntimeError: Agent finished without creating a PR
> ```

This prevents silent failures — the user always sees either a PR or an error message.

---

## 5. Agent Workflow Internals

### 5.1 Workflow Graph

Defined in `workflow.py`:

```python
nodes = {
    "explorer": DiGraphNode(name="explorer", edges=[DiGraphEdge(target="planner")]),
    "planner": DiGraphNode(name="planner", edges=[DiGraphEdge(target="executor")]),
    "executor": DiGraphNode(name="executor", edges=[]),
}
graph = DiGraph(nodes=nodes, default_start_node="explorer")
termination = TextMentionTermination("PR_CREATED") | MaxMessageTermination(20)
team = GraphFlow(participants=[explorer, planner, executor], graph=graph, termination_condition=termination)
```

### 5.2 Execution Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Agent Workflow                                │
│                                                                      │
│  Team.run_stream(task="Fix the add function...")                     │
│                                                                      │
│   Start → Explorer has the turn                                      │
│            │                                                         │
│            ▼                                                         │
│   Explorer calls:                                                     │
│     list_directory("./")                                             │
│     read_file("calculator.py")                                       │
│     read_file("test_calculator.py")                                  │
│   Output: Full file contents + summary of what each file does        │
│            │                                                         │
│            ▼                                                         │
│   Planner receives explorer's output + conversation history           │
│   (No tools — pure LLM reasoning)                                    │
│   Output: Step-by-step fix plan (file: calculator.py, change: ...)   │
│            │                                                         │
│            ▼                                                         │
│   Executor receives planner's plan + conversation history             │
│   Calls:                                                              │
│     fix_and_create_pr(                                                │
│       file_path="calculator.py",                                     │
│       search_text="a - b",                                           │
│       replace_with="a + b",                                          │
│       branch_name="fix-issue-123",                                   │
│       title="Fix add function",                                      │
│       body="Closes #123",                                            │
│     )                                                                │
│   Output: "PR created: https://github.com/..."                       │
│            │                                                         │
│            ▼                                                         │
│   TextMentionTermination("PR_CREATED") → team stops                  │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

### 5.3 Key Property: Full Conversation History

Each agent receives **all previous messages** — not just the last output. When the Executor gets its turn, it sees:
1. The original issue text
2. Explorer's tool calls and responses
3. Explorer's final summary
4. Planner's fix plan

This means each agent has full context without needing a separate message bus.

### 5.4 Termination Conditions

```python
termination = TextMentionTermination("PR_CREATED") | MaxMessageTermination(20)
```

Two ways the workflow stops:
- **Success**: The executor ends its response with "PR_CREATED"
- **Safety limit**: If the model loops or fails to produce a PR after 20 messages, the workflow terminates with an error

---

## 6. Agent Internals (Per Agent)

### 6.1 Explorer Agent

```
System Prompt: "You are a codebase explorer. You MUST call these tools in order:
1. list_directory(path='./')
2. read_file(path='calculator.py')
3. read_file(path='test_calculator.py')
After reading the files, output their COMPLETE contents."

Model receives:
  [SystemMessage] "You are a codebase explorer..."
  [UserMessage]  "The add function returns wrong results, fix it"

Model responds:
  FunctionCall("list_directory", {"path": "./"})
  → Tool result: ["calculator.py", "test_calculator.py", "README.md"]

Model responds:
  FunctionCall("read_file", {"path": "calculator.py"})
  → Tool result: "def add(a, b): return a - b\n..."

Model responds:
  FunctionCall("read_file", {"path": "test_calculator.py"})
  → Tool result: "def test_add(): assert add(1, 2) == 3\n..."

Model outputs:
  "Here are the files:
   calculator.py contains: def add(a, b): return a - b
   The bug is clear: subtraction instead of addition."
```

**Tools**: `list_directory`, `read_file`, `grep_search`  
**Why ordered instructions**: Groq Llama sometimes skips steps. The rigid "MUST call in order" prompt ensures reliable tool chaining.

### 6.2 Planner Agent

```
System Prompt: "You are a senior software engineer. Based on the exploration
findings below, create a detailed step-by-step plan to fix the issue.
IMPORTANT: You do NOT have access to any tools."

Model receives:
  [SystemMessage] "You are a senior software engineer..."
  [UserMessage]  "The add function returns wrong results, fix it"
  [AssistantMessage with tool calls + results]
  [AssistantMessage] "Here are the files: calculator.py contains..."

Model outputs:
  "Fix plan:
   Step 1: Open calculator.py
   Step 2: Change return a - b to return a + b
   Step 3: Commit and create PR"
```

**No tools** — forces the model to reason rather than attempt actions. The explicit "do NOT call tools" prevents the model from trying to use tools on its own.

### 6.3 Executor Agent

```
System Prompt: "You are a developer. Call fix_and_create_pr with the correct
arguments to fix the bug and create a pull request.
End with 'PR_CREATED' when done."

Model receives:
  [SystemMessage] "You are a developer..."
  [UserMessage]  "The add function returns wrong results, fix it"
  [Full conversation from explorer + planner]
  [Planner's plan]

Model responds:
  FunctionCall("fix_and_create_pr", {
    "file_path": "calculator.py",
    "search_text": "a - b",
    "replace_with": "a + b",
    "branch_name": "fix-issue-1",
    "title": "Fix add function",
    "body": "Closes #1\n\nChanged subtraction to addition.",
  })
  → Tool result: "PR created: https://github.com/Tikam321/test-calculator/pull/5"

Model outputs:
  "PR_CREATED"
```

**Single tool** — `fix_and_create_pr` bundles read, edit, commit, push, and PR creation into one call. This is intentional: Groq Llama often fails to chain multiple independent tool calls, so a single end-to-end tool is more reliable.

---

## 7. The `fix_and_create_pr` Tool (Deep Dive)

### 7.1 Location

`tools/git_tools.py:fix_and_create_pr()`

### 7.2 Parameters

| Parameter | Type | Description |
|---|---|---|
| `file_path` | `str` | Relative path to file to fix (e.g. `calculator.py`) |
| `search_text` | `str` | Text to find (substring or multiline) |
| `replace_with` | `str` | Text to replace with |
| `branch_name` | `str` | Git branch name (e.g. `fix-issue-1`) |
| `title` | `str` | PR title |
| `body` | `str` | PR body |
| `base` | `str` | Base branch (default `master`) |

### 7.3 Internal Flow

```
fix_and_create_pr(...)
    │
    ├── 1. Read file content
    │      Path(file_path).read_text()
    │
    ├── 2. Try exact match first
    │      if search_text in data:
    │          data = data.replace(search_text, replace_with, 1)
    │
    ├── 3. Fallback: line-by-line match
    │      Split search_text by newlines → search_lines[]
    │      Split replace_with by newlines  → replace_lines[]
    │      For each search_line:
    │          if search_line.strip() in data:
    │              data = data.replace(search_line.strip(), 
    │                                  replace_lines[i].strip(), 1)
    │              break
    │      If no line matches → return "Error: could not find..."
    │
    ├── 4. Write fixed content
    │      Path(file_path).write_text(data)
    │
    └── 5. create_full_pr(branch_name, file_path, title, body, base)
           │
           ├── a. Remove stale .git/index.lock
           ├── b. setup_git_auth() — inject token into origin URL
           ├── c. _parse_remote_owner_repo()
           │     git remote get-url origin
           │     Strip auth token from URL
           │     Parse "owner/repo" from URL
           ├── d. git checkout base
           ├── e. git checkout -B branch_name  (creates or resets branch)
           ├── f. git add file_path
           ├── g. git commit -m "title"
           ├── h. git push --force origin branch_name
           └── i. create_pr(owner, repo, title, body, head, base)
                  │
                  ├── GET /repos/owner/repo/pulls?state=open&head=owner:branch
                  │   For each existing PR from this branch → PATCH state=closed
                  └── POST /repos/owner/repo/pulls → returns {html_url: "..."}
```

### 7.4 The Line-by-Line Fallback

Why it exists: When the LLM generates `search_text`, it might include slightly different whitespace or formatting than what's in the file. The fallback strips each line and tries to find it independently. This fixed a real bug where PR #4 was created with no changes because the multiline search text didn't exactly match.

### 7.5 Auto-Close Existing PRs

```python
search = GET /repos/{owner}/{repo}/pulls?state=open&head={owner}:{head}
for pr in existing:
    if pr["head"]["ref"] == head:
        PATCH pr["url"] → {"state": "closed"}
```

If the same issue triggers multiple runs, each new run force-pushes to the same branch and closes the old PR before creating a new one. This prevents duplicate PRs piling up.

---

## 8. LLM Client: `RawGroqClient`

### 8.1 Why a Custom Client?

AutoGen's `OpenAIChatCompletionClient` sends `strict: false` and `additionalProperties: false` in tool schemas. Groq's Llama model interprets these fields as a signal to switch to an XML-style tool call format:

```xml
<function=read_file>{"path": "calculator.py"}</function>
```

instead of the standard OpenAI JSON format:

```json
{
  "tool_calls": [{
    "id": "call_123",
    "function": {"name": "read_file", "arguments": "{\"path\": \"calculator.py\"}"}
  }]
}
```

AutoGen doesn't understand the XML format, so tool calls silently fail.

### 8.2 How `RawGroqClient` Works

```
Create(...)
    │
    ├── _to_openai_messages(messages)  — Convert AutoGen message types → OpenAI format
    │   SystemMessage  → {"role": "system", "content": ...}
    │   UserMessage    → {"role": "user", "content": ...}
    │   AssistantMessage → {"role": "assistant", "tool_calls": [...]}
    │   FunctionExecutionResultMessage → {"role": "tool", ...}
    │
    ├── _openai_tools(tools) — Strip problematic fields
    │   Remove "strict"
    │   Remove "additionalProperties" from parameters
    │
    ├── Call AsyncOpenAI SDK directly (bypass AutoGen's client)
    │
    ├── Handle tool_use_failed errors (retry up to 3 times)
    │
    ├── Parse response
    │   If msg.tool_calls → convert to AutoGen FunctionCall list
    │   If text response → check for XML <function=...> tags via _extract_xml_tool_calls()
    │     If XML found → convert to FunctionCall list
    │     Else → return as plain text
    │
    └── Return CreateResult (content, usage, finish_reason)
```

### 8.3 XML Post-Processing

```python
_FUNCTION_XML_RE = re.compile(
    r"<function=(\w+)>\s*(\{.*?\}|`[^`]+`)\s*</function>",
    re.DOTALL,
)
```

If the model returns XML-style tool calls despite the fixes, the regex extracts them and converts to AutoGen's `FunctionCall` format — a second line of defense.

---

## 9. Repo Manager: Clone + Cleanup

### 9.1 Clone with Token Auth

```python
def clone_repo(clone_url: str, token: str) -> str:
    work_dir = tempfile.mkdtemp(prefix="pr-agent-")
    authed_url = clone_url.replace("https://", f"https://x-access-token:{token}@")
    result = subprocess.run(
        ["git", "clone", "--depth", "1", authed_url, work_dir],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise RuntimeError(f"Clone failed: {result.stderr.strip()}")
    return work_dir
```

Why `--depth 1`: We only need the current state of the code to read and fix. A full history is unnecessary for the agent's analysis.

### 9.2 Parallel Safety

Each webhook request gets its own `tempfile.mkdtemp()` directory. Multiple concurrent requests (from different repos or issues) are fully isolated — they don't share filesystem state.

### 9.3 Cleanup

```python
def cleanup_repo(work_dir: str):
    if work_dir and os.path.isdir(work_dir):
        shutil.rmtree(work_dir, ignore_errors=True)
```

Always called in a `finally` block, so temp directories are never left behind even if the agent crashes.

---

## 10. Deployment Architecture

### 10.1 Local Development

```
┌──────────┐     ngrok      ┌───────────┐
│  GitHub   │──────────────▶│  localhost │
│  Webhook  │   HTTPS       │  :8000     │
└──────────┘                └───────────┘
```

- Server: `uv run python -m uvicorn server.app:app --port 8000`
- Tunnel: `ngrok http 8000` → `https://xxxx.ngrok-free.dev`
- GitHub App webhook URL → ngrok URL + `/webhook`

### 10.2 Production (Render)

```
┌──────────┐               ┌──────────────────┐
│  GitHub   │──────────────▶│    Render.com    │
│  Webhook  │   HTTPS       │  pr-autogen-agent│
└──────────┘               │  (Docker)         │
                            │  PORT=8000        │
                            └──────────────────┘
```

- Dockerfile: `python:3.14-slim` + `uv` sync + `uvicorn server.app:app`
- Render blueprint (`render.yaml`): free tier, Docker env, env vars set via dashboard
- No ngrok needed — Render provides a public HTTPS URL

### 10.3 Environment Variables

| Variable | Purpose | Source |
|---|---|---|
| `GROQ_API_KEY` | LLM provider | Groq dashboard |
| `GITHUB_TOKEN` | Fallback auth (PAT) | GitHub settings |
| `GITHUB_APP_ID` | GitHub App identifier | GitHub App settings page |
| `GITHUB_PRIVATE_KEY` | RSA key for JWT signing | GitHub App → Generate private key |
| `GITHUB_WEBHOOK_SECRET` | HMAC secret for webhook verification | Random string you generate |

---

## 11. Key Design Decisions

### 11.1 3 Agents Instead of 6

**Original design**: Explorer → Planner → Fixer → Reviewer → PR Creator → Feedback Handler (6 agents with loops)

**Current**: Explorer → Planner → Executor (3 agents, linear)

**Why**: Groq's Llama 3.3 70B doesn't reliably chain multiple tool calls across multiple agents. Breaking the fix-and-PR-creation into separate agents (Fixer → Reviewer → PR Creator) caused failures because the LLM would forget context between turns. Bundling everything into `fix_and_create_pr` (single tool, one agent) is more reliable.

### 11.2 Single `fix_and_create_pr` Tool vs. Multiple Tools

**Alternative**: Give the executor separate `read_file`, `write_file`, `git_commit`, `git_push`, `create_pr` tools and let the LLM chain them.

**Chosen**: One `fix_and_create_pr` tool that does everything.

**Why**: The LLM often calls tools in the wrong order, forgets intermediate results, or fails to pass correct arguments between chained calls. A single function call eliminates all those failure modes.

### 11.3 `--depth 1` Clone

**Alternative**: Full clone with history.

**Chosen**: Shallow clone.

**Why**: The agent only needs the current file contents, not git history. A full clone of a large repo (e.g., 10k+ commits) takes significantly longer and uses more disk space.

### 11.4 Force Push + Auto-Close

**Alternative**: Create a new branch name each time (e.g., `fix-issue-1-v2`).

**Chosen**: Same branch name, force push, auto-close old PR.

**Why**: If the same issue triggers multiple runs (e.g., the first fix was wrong), using the same branch name keeps things clean. Old PRs are automatically closed so the repo doesn't accumulate stale PRs from the same issue.

### 11.5 Line-by-Line Search Fallback

**Alternative**: Require exact string match.

**Chosen**: Try exact match first, then line-by-line.

**Why**: The LLM generates `search_text` with possible whitespace differences. The fallback strips whitespace and matches individual lines, which handles most formatting mismatches.

### 11.6 Background Tasks (`asyncio.create_task`)

**Alternative**: Process the webhook synchronously.

**Chosen**: Return 200 immediately, process in background.

**Why**: GitHub expects a webhook response within 10 seconds. The agent workflow takes 30-60 seconds. Background tasks solve this without requiring a separate job queue.

### 11.7 Error Commenting

**Alternative**: Log errors silently or return HTTP 500.

**Chosen**: Post a comment on the issue with the error message.

**Why**: Silent failures are bad UX — the user opens an issue and gets nothing back. A comment tells them the agent tried but failed, and gives them the error to debug.

---

## 12. Security Considerations

### 12.1 Private Key Storage

- The `.pem` file is stored in `.env` (single line with `\n` escapes)
- `.env` is in `.gitignore` — never committed
- Render stores it as a secret environment variable (not visible in logs)

### 12.2 Token Scope

- Each installation token is valid for 1 hour and scoped to one repo
- If a token leaks, the attacker can only access that one repo for 1 hour
- No user password or PAT is involved

### 12.3 Webhook Verification

- Every webhook payload includes a signature: `sha256=HMAC(payload, secret)`
- Invalid signatures are rejected with HTTP 401
- Prevents attackers from faking webhook requests

### 12.4 Filesystem Isolation

- Each request clones into a separate `mkdtemp` directory
- Multiple concurrent requests from different repos don't interfere
- Cleanup runs in `finally` — no temp directories left behind

---

## 13. Error Handling Matrix

| Failure Point | What Happens | User Sees |
|---|---|---|
| Webhook signature invalid | HTTP 401 | GitHub retries webhook |
| Clone fails | RuntimeError → comment on issue | Error comment on issue |
| Agent times out (20 messages) | MaxMessageTermination → no PR URL | Error comment |
| Agent returns no PR URL | RuntimeError("Agent finished without...") | Error comment |
| Installation token expires | HTTP 401 from GitHub API → unhandled exception | Error comment |
| Private key invalid | JWT encode fails → server crash | Error comment |
| Git push fails | RuntimeError from subprocess | Error comment |
| PR creation fails | HTTP error from GitHub API | Error comment |

---

## 14. File-by-File Internal Summary

| File | Lines | What It Does |
|---|---|---|
| `config.py` | ~200 | Custom `RawGroqClient` that bypasses AutoGen's tool call issues; maintains multiple provider instances (Groq, OpenRouter, NVIDIA, DeepSeek, Mistral, Google) |
| `workflow.py` | ~20 | 3-node `DiGraph`: explorer → planner → executor; termination on PR_CREATED or 20 messages |
| `agents/explorer.py` | ~20 | AssistantAgent with `read_file`, `grep_search`, `list_directory`; rigid prompt to force ordered tool calls |
| `agents/planner.py` | ~15 | AssistantAgent with no tools; pure LLM reasoning to create fix plan |
| `agents/executor.py` | ~15 | AssistantAgent with single `fix_and_create_pr` tool; ends with "PR_CREATED" |
| `tools/file_tools.py` | ~50 | 5 FunctionTools: read, write, edit, grep, list_directory — all operate on local filesystem |
| `tools/git_tools.py` | ~180 | `fix_and_create_pr` (line-based replace + create_full_pr), `create_full_pr` (auth + branch + commit + push + PR), `create_pr` (API call with auto-close), `setup_git_auth`, `_parse_remote_owner_repo`, `add_pr_comment`, `get_pr_comments` |
| `server/auth.py` | ~35 | `_get_jwt()` (RS256 JWT from private key), `get_installation_token()` (exchange JWT for token) |
| `server/webhook.py` | ~75 | `verify_signature()` (HMAC-SHA256), `process_issue()` (auth → clone → run → cleanup → error comment), FastAPI POST `/webhook` |
| `server/repo_manager.py` | ~40 | `clone_repo()` (--depth 1 with token auth), `cleanup_repo()` (rmtree), `comment_on_issue()` (POST GitHub API) |
| `server/runner.py` | ~30 | `run_agent()` (chdir → agent workflow → extract PR URL from TaskResult), `_extract_pr_url()` (parses "PR created: URL" from agent output) |
| `server/app.py` | ~10 | FastAPI app with `/health` endpoint and webhook router |
| `main.py` | ~45 | CLI: reads issue from argv or stdin, runs agent workflow, prints PR URL |
| `Dockerfile` | ~10 | python:3.14-slim + uv + port 8000 |
| `render.yaml` | ~15 | Render free-tier Docker blueprint with env vars |

---

## 15. Data Flow Diagrams

### 15.1 Webhook Path (Full Request)

```
GitHub                        Server                           Target Repo
  │                              │                                │
  │ POST /webhook                │                                │
  │ X-GitHub-Event: issues       │                                │
  │ {issue, repository,          │                                │
  │  installation}               │                                │
  │─────────────────────────────▶│                                │
  │                              │                                │
  │                              │ verify_signature(payload, sig) │
  │                              │ parse JSON payload             │
  │                              │ check event == "issues"        │
  │                              │ check action == "opened"       │
  │                              │                                │
  │ 200 {"ok": true}             │                                │
  │◀─────────────────────────────│                                │
  │                              │                                │
  │                              │ asyncio.create_task()          │
  │                              │                                │
  │                              │ _get_jwt()                     │
  │                              │   ├── load PRIVATE_KEY from env│
  │                              │   └── RS256 sign {iss, iat,   │
  │                              │        exp}                    │
  │                              │                                │
  │                              │ POST /app/installations/       │
  │                              │      {id}/access_tokens        │
  │                              │ Authorization: Bearer <JWT>    │
  │                              │───────────────────────────────▶│
  │                              │                                │
  │                              │ 200 {token: "ghs_..."}         │
  │                              │◀───────────────────────────────│
  │                              │                                │
  │                              │ git clone --depth 1            │
  │                              │ https://x-access-token:        │
  │                              │   ghs_...@github.com/          │
  │                              │   owner/repo                   │
  │                              │───────────────────────────────▶│
  │                              │                                │
  │                              │ (Agent workflow: 3 rounds)     │
  │                              │   read file, fix, commit, push │
  │                              │                                │
  │                              │ POST /repos/owner/repo/pulls   │
  │                              │ Authorization: Bearer ghs_...  │
  │                              │───────────────────────────────▶│
  │                              │                                │
  │                              │ 201 {html_url: "..."}          │
  │                              │◀───────────────────────────────│
  │                              │                                │
  │                              │ cleanup_repo()                 │
  │                              │ (rm -rf temp dir)              │
```

### 15.2 CLI Path

```
User                                          Server
  │                                              │
  │ uv run python main.py "Fix add function"     │
  │─────────────────────────────────────────────▶│
  │                                              │
  │                                              │ os.chdir(repo_dir)
  │                                              │ team.run_stream(task=issue)
  │                                              │   ├── explorer reads files
  │                                              │   ├── planner creates plan
  │                                              │   └── executor calls fix_and_create_pr
  │                                              │
  │ PR URL: https://github.com/.../pull/5        │
  │◀─────────────────────────────────────────────│
```

---

## 16. Key Files Reference

| File | Purpose |
|---|---|
| `config.py` | LLM client factory — switch providers here |
| `workflow.py` | Agent topology — change agent order here |
| `agents/explorer.py` | Codebase scanning logic |
| `agents/planner.py` | Fix plan generation (prompt only) |
| `agents/executor.py` | Fix implementation + PR creation |
| `tools/git_tools.py` | `fix_and_create_pr` — the core automation tool |
| `server/webhook.py` | Webhook receiver — entry point for production |
| `server/auth.py` | GitHub App authentication |
| `server/repo_manager.py` | Clone/cleanup/comment |
| `server/runner.py` | Agent invocation in cloned repo |
