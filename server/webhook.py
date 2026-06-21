import os
import asyncio
import hashlib
import hmac
from fastapi import APIRouter, Request, HTTPException
from dotenv import load_dotenv
from server.auth import get_installation_token
from server.repo_manager import clone_repo, cleanup_repo, comment_on_issue
from server.runner import run_agent

load_dotenv()

WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")
router = APIRouter()


def verify_signature(payload: bytes, signature_header: str) -> bool:
    if not WEBHOOK_SECRET or not signature_header:
        return False
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


async def process_issue(
    installation_id: int, clone_url: str,
    owner: str, repo: str, issue_number: int,
    issue_title: str, issue_body: str,
):
    issue_text = f"{issue_title}\n\n{issue_body}" if issue_body else issue_title
    token = get_installation_token(installation_id)
    repo_dir = clone_repo(clone_url, token)
    try:
        result = await run_agent(repo_dir, issue_text)
        if not result:
            raise RuntimeError("Agent finished without creating a PR")
        return result
    except Exception as e:
        comment_on_issue(token, owner, repo, issue_number, f"🤖 **PR Autogen Agent failed**\n\n```\n{e}\n```")
        raise
    finally:
        cleanup_repo(repo_dir)


@router.post("/webhook")
async def github_webhook(request: Request):
    body = await request.body()
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(body, sig):
        raise HTTPException(401, "Invalid signature")

    event = request.headers.get("X-GitHub-Event", "")
    payload = await request.json()

    if event == "issues" and payload.get("action") == "opened":
        installation_id = payload["installation"]["id"]
        clone_url = payload["repository"]["clone_url"]
        owner = payload["repository"]["owner"]["login"]
        repo = payload["repository"]["name"]
        issue_number = payload["issue"]["number"]
        issue_title = payload["issue"]["title"]
        issue_body = payload["issue"]["body"]

        asyncio.create_task(
            process_issue(
                installation_id, clone_url,
                owner, repo, issue_number,
                issue_title, issue_body,
            )
        )

    return {"ok": True}
