# Deployment Architectures

Two ways to make the agent workflow publicly usable:

## Option A: GitHub Actions (self-use)

The user adds a workflow YAML to their repo. GitHub's runner clones the repo, runs our agent pipeline, and creates a PR — all inside GitHub's infrastructure.

```
User's Repo
│
Issue: "Fix add function bug"
│
▼
GitHub Actions Runner
│
├── 1. Checkout repo (git clone)
├── 2. Install deps (uv sync)
├── 3. Run agent workflow (same pipeline)
│      Explorer → Planner → Fixer → Reviewer → PR Creator
│
├── 4. git checkout -b fix/add-function
├── 5. git add <files> && git commit
├── 6. git push origin fix/add-function
└── 7. PR created
```

**Auth:**
- `GITHUB_TOKEN` auto-injected by GitHub Actions — full write access to the repo, no setup
- User sets `GROQ_API_KEY` as a repo secret once

**User setup:**
1. Create `.github/workflows/pr-autogen.yml`
2. Add `GROQ_API_KEY` to repo secrets

**Pros:** Serverless, zero hosting cost, minimal setup.
**Cons:** Only works on GitHub, limited to 6h runtime.

---

## Option B: GitHub App + Webhook Server (public use)

Other users install a GitHub App on their repo. When they open an issue, GitHub sends a webhook to our server, which runs the agent workflow and creates a PR on their repo.

```
Our Server (Render / Fly.io / Railway)
│
┌──────────────────┐
│  Webhook Handler │◄──── POST /webhook (issue body, repo_url)
│  (FastAPI)       │
└──────┬───────────┘
       │
┌──────▼───────────┐
│  Auth Manager    │──── Generates installation token (scoped per-repo)
│  (GitHub App JWT)│
└──────┬───────────┘
       │
┌──────▼───────────┐
│  Clone Repo      │──── git clone https://x-access-token:TOKEN@github.com/...
│  (temp directory)│
└──────┬───────────┘
       │
┌──────▼───────────┐
│  Agent Workflow  │──── Same pipeline as current code
│  (run_stream)    │
└──────┬───────────┘
       │
┌──────▼───────────┐
│  Push + Create PR│──── git push + POST /repos/.../pulls
└──────────────────┘
       │
       ▼
    PR created on user's repo
```

**Auth flow:**
1. User installs GitHub App on their repo
2. GitHub sends installation ID to our webhook
3. Our server generates a **short-lived installation token** (JWT) via GitHub App API
4. Token is scoped to only that repo, only the permissions we requested

**Server setup:**
- FastAPI app with a `/webhook` endpoint
- Handles `issues` and `installation` events
- Clone repo → run agent → push PR → cleanup temp dir

**User setup:** Click "Install" on our GitHub App page. That's it.

**Pros:** One-click for users, works for any GitHub user, no YAML/config.
**Cons:** Needs a hosted server, more complex auth.

---

## Comparison

| Aspect | GitHub Actions | GitHub App |
|---|---|---|
| Who runs it | User's repo (GitHub infra) | Our server |
| User setup | Add YAML + secret | Click "Install" |
| Auth | Auto-injected token | Installation JWT token |
| Hosting cost | $0 | ~$0-5/mo |
| Runtime limit | 6 hours | Unlimited |
| Best for | Devs, internal team use | Public, non-technical users |
