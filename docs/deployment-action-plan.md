# Deployment Action Plan — Render

## Overview

Deploy the PR Autogen Agent server to Render's free Docker tier so the GitHub App processes issues 24/7 without requiring ngrok on your local machine.

**Estimated time**: ~15 minutes

---

## Prerequisites

- [ ] Render account (sign up at https://dashboard.render.com if not already)
- [ ] GitHub App Issues permission set to **Read & write** (already done)
- [ ] `.env` file with all 5 keys populated

---

## Step 1 — Push code to GitHub

```bash
git add Dockerfile .dockerignore render.yaml \
       server/ tools/ agents/ workflow.py config.py main.py \
       pyproject.toml uv.lock .env.example docs/
git commit -m "Ready for Render deployment"
git push origin main
```

**What this does**: Stages all source files, Docker config, and the lockfile. The `.dockerignore` prevents `.env` (secrets) from being included in the Docker image.

---

## Step 2 — Deploy on Render

1. Go to https://dashboard.render.com
2. Click **New +** → **Blueprint**
3. Connect your GitHub repository (`Tikam321/pr-autogen-agent`)
4. Render reads `render.yaml` and creates a web service named `pr-autogen-agent`
5. The first deploy will **fail** — env vars aren't set yet

---

## Step 3 — Set environment variables

In Render dashboard → your service → **Environment** → add these:

| Key | Value | Source |
|---|---|---|
| `GITHUB_APP_ID` | `4108243` | GitHub App settings page |
| `GITHUB_PRIVATE_KEY` | Full private key (single line with `\n`) | GitHub App → Generate private key |
| `GITHUB_WEBHOOK_SECRET` | Your webhook secret | Random string you created |
| `GROQ_API_KEY` | `gsk_Bxgwow1stIESH...` | Your `.env` |
| `GITHUB_TOKEN` | `ghp_0Q2GnWyJlnp...` | Your `.env` |

After saving, Render automatically re-deploys. Wait for the deploy to show **Live**.

---

## Step 4 — Update GitHub App webhook URL

1. Go to GitHub **Settings** → **Developer settings** → **GitHub Apps** → `pr-autogen-agent`
2. Scroll to **Webhook URL**
3. Change from: `https://supremacy-python-polygon.ngrok-free.dev/webhook`
4. Change to: `https://pr-autogen-agent.onrender.com/webhook`
   *(Note: Render may assign a different URL like `pr-autogen-agent-xx.onrender.com` — check your Render dashboard for the exact URL)*
5. Click **Save changes**

---

## Step 5 — Test

1. Open a new issue on `Tikam321/test-calculator`:
   > "The add function returns wrong results, fix it"
2. Check Render logs (Dashboard → your service → **Logs**) for:
   ```
   [webhook] Processing issue #N in Tikam321/test-calculator
   [webhook] Getting installation token...
   [webhook] Cloning repo...
   [webhook] Running agent workflow...
   [webhook] PR created: https://github.com/Tikam321/test-calculator/pull/N
   ```
3. Verify the PR appears on the repo with correct changes

---

## Post-Deployment Notes

- **Free tier sleep**: Render free instances spin down after 15 minutes of inactivity. The first webhook after idle takes ~30 seconds to cold-start. GitHub retries webhooks for up to 24 hours, so the issue will still be processed — just with a delay.
- **Logs**: View logs at Render dashboard → your service → **Logs** tab
- **Redeploy on push**: Any future `git push` to `main` triggers an automatic redeploy

---

## Rollback

If something goes wrong:

1. **Revert webhook URL**: Change GitHub App webhook URL back to `https://supremacy-python-polygon.ngrok-free.dev/webhook`
2. **Revert code**: `git revert HEAD && git push origin main`
3. **Restart ngrok**: `ngrok http 8000` + `uv run python -m uvicorn server.app:app --port 8000`
