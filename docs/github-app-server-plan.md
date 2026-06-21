# GitHub App Server — Implementation Plan

17 steps to deploy a public GitHub App that auto-fixes issues with PRs.

---

## Phase 1: Prepare the Agent Code for Server Use

### Step 1 — Update `main.py`

Accept issue as CLI argument instead of hardcoded text. Accept optional repo URL.

**Input:** `uv run python main.py "Fix the add function bug"`  
**Output:** PR URL printed to stdout

```
main.py
├── sys.argv → issue text
├── import workflow.team
├── run team.run_stream(task=issue)
└── print PR URL
```

### Step 2 — Update Dependencies

Add server dependencies to `pyproject.toml`:

```
fastapi
uvicorn[standard]
PyJWT
cryptography
```

**Command:** `uv add fastapi uvicorn[standard] pyjwt cryptography`

### Step 3 — Update `.env.example`

Add GitHub App credentials:

```
GROQ_API_KEY=
GITHUB_TOKEN=
GITHUB_APP_ID=
GITHUB_PRIVATE_KEY=
GITHUB_WEBHOOK_SECRET=
```

---

## Phase 2: Build the Server

### Step 4 — GitHub Auth Module `server/auth.py`

Two functions:

```python
def generate_jwt(app_id: str, private_key_pem: str) -> str:
    """Sign a JWT with the GitHub App private key (RS256)."""
    # payload: { iss: app_id, iat: now - 60s, exp: now + 600s }
    # encode with RSA key

def get_installation_token(installation_id: int, jwt: str) -> str:
    """Exchange JWT for a short-lived installation access token."""
    # POST https://api.github.com/app/installations/{id}/access_tokens
    # return token["token"]
```

### Step 5 — Webhook Handler `server/webhook.py`

```python
@router.post("/webhook")
async def github_webhook(request: Request):
    payload = await request.json()

    # Verify webhook signature using GITHUB_WEBHOOK_SECRET
    # Parse event based on X-GitHub-Event header

    if event == "issues" and action == "opened":
        issue_title = payload["issue"]["title"]
        issue_body = payload["issue"]["body"]
        clone_url = payload["repository"]["clone_url"]
        installation_id = payload["installation"]["id"]

        # Run in background task
        asyncio.create_task(process_issue(installation_id, clone_url, issue_body))

    return {"ok": True}
```

### Step 6 — Repo Manager `server/repo_manager.py`

```python
import tempfile, shutil, subprocess

def clone_repo(clone_url: str, token: str) -> str:
    """Clone repo to a temp directory and return the path."""
    work_dir = tempfile.mkdtemp()
    authed_url = clone_url.replace("https://", f"https://x-access-token:{token}@")
    subprocess.run(["git", "clone", authed_url, work_dir], check=True)
    return work_dir

def cleanup_repo(work_dir: str):
    """Remove cloned repo."""
    shutil.rmtree(work_dir, ignore_errors=True)
```

### Step 7 — Runner `server/runner.py`

```python
from workflow import team

async def run_agent(repo_dir: str, issue_text: str) -> str:
    """Run agent workflow in repo_dir and return PR URL."""
    original_cwd = os.getcwd()
    os.chdir(repo_dir)

    try:
        async for message in team.run_stream(task=issue_text):
            if isinstance(message, TaskResult):
                for m in message.messages:
                    content = str(getattr(m, "content", ""))
                    if "PR created:" in content:
                        return content.split("PR created:")[-1].strip()
        raise RuntimeError("PR_CREATED not found in agent output")
    finally:
        os.chdir(original_cwd)
```

### Step 8 — FastAPI App `server/app.py`

```python
from fastapi import FastAPI
from server.webhook import router as webhook_router

app = FastAPI(title="PR Autogen Agent")
app.include_router(webhook_router)

@app.get("/health")
async def health():
    return {"status": "ok"}
```

**Full server flow:**

```
/webhook POST
  │
  ├── 1. Verify webhook signature
  ├── 2. Parse issue title + body, clone_url, installation_id
  ├── 3. Generate JWT → get installation token
  ├── 4. git clone repo to temp dir
  ├── 5. os.chdir → repo dir
  ├── 6. Run agent workflow (fix + create PR)
  ├── 7. os.chdir → back
  ├── 8. Delete temp dir
  └── 9. Return 200 { "pr_url": "..." }
```

---

## Phase 3: Deploy

### Step 9 — Dockerfile

```dockerfile
FROM python:3.14-slim
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen
COPY . .
CMD ["uv", "run", "uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Step 10 — Platform Config

**Render** (`render.yaml`):
```yaml
services:
  - type: web
    name: pr-autogen-agent
    env: docker
    plan: free
    envVars:
      - key: GROQ_API_KEY
        sync: false
      - key: GITHUB_APP_ID
        sync: false
      - key: GITHUB_PRIVATE_KEY
        sync: false
      - key: GITHUB_WEBHOOK_SECRET
        sync: false
```

**Fly.io** (`fly.toml`):
```toml
[env]
  GROQ_API_KEY = "..."
  GITHUB_APP_ID = "..."
app = "pr-autogen-agent"
[services]
  internal_port = 8000
```

**Railway:** Connect GitHub repo → set env vars in dashboard → deploy.

### Step 11 — Deploy

1. Push to GitHub
2. Connect repo to Render / Fly.io / Railway
3. Set all environment variables in the dashboard
4. Deploy → get public URL like `https://pr-autogen-agent.onrender.com`

---

## Phase 4: GitHub App Registration

### Step 12 — Create GitHub App

1. Go to `https://github.com/settings/apps/new`
2. **App name:** `pr-autogen-agent` (must be unique globally)
3. **Homepage URL:** `https://github.com/Tikam321/pr-autogen-agent`
4. **Webhook URL:** `https://your-server.onrender.com/webhook`
5. **Webhook secret:** random string (save in env vars)
6. **Permissions:**

| Permission | Access |
|---|---|
| Issues | Read-only |
| Contents | Read & write |
| Pull requests | Read & write |

7. **Subscribe to events:** `Issues`
8. **Where can this app be installed?** Any repo
9. Click **Create GitHub App**
10. Scroll down → **Generate a private key** → save `.pem` file

### Step 13 — Configure Server Env Vars

```
GITHUB_APP_ID=123456                    # from app page top
GITHUB_PRIVATE_KEY="-----BEGIN RSA..."  # from .pem file (on one line with \n)
GITHUB_WEBHOOK_SECRET=abc123...         # the secret you set
GROQ_API_KEY=gsk-...                    # existing key
```

### Step 14 — Install App

1. On GitHub App page → **Install App** → select your repos
2. Or: `https://github.com/apps/pr-autogen-agent/installations/new`

---

## Phase 5: Test & Launch

### Step 15 — Local Test with ngrok

```bash
# Terminal 1: Start server
uv run uvicorn server.app:app --reload --port 8000

# Terminal 2: Expose with ngrok
ngrok http 8000
```

1. Update GitHub App webhook URL to `https://your-ngrok.ngrok.io/webhook`
2. Open an issue on the test repo
3. Verify PR is created

### Step 16 — Production Test

1. Update webhook URL to production URL
2. Open an issue on a test repo
3. Check server logs for any errors
4. Verify PR diff is correct

### Step 17 — Make Public

1. In GitHub App settings → **Public** → make app public
2. Add install badge to README:
   ```markdown
   [![Install](https://img.shields.io/badge/Install-GitHub%20App-blue)](https://github.com/apps/pr-autogen-agent/installations/new)
   ```
3. Add `/install` endpoint that redirects to install URL
4. Document usage in README

---

## Effort Estimate

| Phase | Steps | Est. Time |
|---|---|---|
| Phase 1: Agent prep | 1-3 | 30 min |
| Phase 2: Build server | 4-8 | 2-3 hours |
| Phase 3: Deploy | 9-11 | 1 hour |
| Phase 4: GitHub App | 12-14 | 1 hour |
| Phase 5: Test & launch | 15-17 | 1-2 hours |
| **Total** | **17 steps** | **~6-8 hours** |
