import os
import json
import shutil
import subprocess
import tempfile
import urllib.request


def comment_on_issue(token: str, owner: str, repo: str, issue_number: int, body: str):
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/comments"
    req = urllib.request.Request(
        url,
        data=json.dumps({"body": body}).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req):
        pass


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


def cleanup_repo(work_dir: str):
    if work_dir and os.path.isdir(work_dir):
        shutil.rmtree(work_dir, ignore_errors=True)
