import os
import json
import urllib.request
import urllib.error
from dotenv import load_dotenv
from autogen_ext.code_executors.local import LocalCommandLineCodeExecutor
from autogen_agentchat.agents import CodeExecutorAgent

load_dotenv()

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")


def _get_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "autogen-pr-agent",
    }


def setup_git_auth(repo_dir: str = ".") -> None:
    """Inject the token into the origin remote URL so git push works."""
    import subprocess
    origin = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True, text=True, cwd=repo_dir,
    ).stdout.strip()
    if "https://" in origin and "@" not in origin:
        # https://github.com/owner/repo → https://x-access-token:TOKEN@github.com/owner/repo
        authed = origin.replace("https://", f"https://x-access-token:{GITHUB_TOKEN}@")
        subprocess.run(["git", "remote", "set-url", "origin", authed], cwd=repo_dir)


git_executor = LocalCommandLineCodeExecutor()
git_agent = CodeExecutorAgent("git_executor", code_executor=git_executor)


def create_pr(owner: str, repo: str, title: str, body: str, head: str, base: str = "main") -> dict:
    data = json.dumps({"title": title, "body": body, "head": head, "base": base}).encode()
    req = urllib.request.Request(
        f"https://api.github.com/repos/{owner}/{repo}/pulls",
        data=data,
        headers=_get_headers(),
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def add_pr_comment(owner: str, repo: str, pr_number: int, comment: str) -> dict:
    data = json.dumps({"body": comment}).encode()
    req = urllib.request.Request(
        f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments",
        data=data,
        headers=_get_headers(),
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def get_pr_comments(owner: str, repo: str, pr_number: int) -> list:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments",
        headers=_get_headers(),
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())
