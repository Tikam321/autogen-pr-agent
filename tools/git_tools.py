import os
import json
import shlex
import subprocess
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


def setup_git_auth(repo_dir: str = ".") -> str:
    """Inject the token into the origin remote URL so git push works."""
    import subprocess
    origin = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True, text=True, cwd=repo_dir,
    ).stdout.strip()
    if "https://" in origin and "@" not in origin:
        authed = origin.replace("https://", f"https://x-access-token:{GITHUB_TOKEN}@")
        subprocess.run(["git", "remote", "set-url", "origin", authed], cwd=repo_dir)
        return f"Git auth configured: origin → {authed[:40]}..."
    return f"Git auth already configured or not needed (origin: {origin[:60]})"


git_executor = LocalCommandLineCodeExecutor()
git_agent = CodeExecutorAgent("git_executor", code_executor=git_executor)


def create_pr(owner: str, repo: str, title: str, body: str, head: str, base: str = "main") -> dict:
    # Close any existing open PRs from this head branch
    search = urllib.request.Request(
        f"https://api.github.com/repos/{owner}/{repo}/pulls?state=open&head={owner}:{head}",
        headers=_get_headers(),
    )
    try:
        with urllib.request.urlopen(search) as resp:
            existing = json.loads(resp.read())
        for pr in existing:
            if pr.get("head", {}).get("ref") == head:
                close_data = json.dumps({"state": "closed"}).encode()
                close_req = urllib.request.Request(
                    pr["url"], data=close_data, headers=_get_headers(), method="PATCH"
                )
                urllib.request.urlopen(close_req)
    except Exception:
        pass

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


def fix_and_create_pr(
    file_path: str,
    search_text: str,
    replace_with: str,
    branch_name: str,
    title: str,
    body: str,
    base: str = "master",
) -> str:
    """Fix a file, commit, push, and create a PR — all in one call."""
    from pathlib import Path

    data = Path(file_path).read_text(encoding="utf-8")

    if search_text in data:
        data = data.replace(search_text, replace_with, 1)
    else:
        search_lines = [ln.strip() for ln in search_text.split("\n") if ln.strip()]
        replace_lines = [ln.strip() for ln in replace_with.split("\n") if ln.strip()]
        for i, sl in enumerate(search_lines):
            if sl in data:
                rl = replace_lines[i] if i < len(replace_lines) else sl
                data = data.replace(sl, rl, 1)
                break
        else:
            return f"Error: could not find matching text in {file_path}"

    Path(file_path).write_text(data, encoding="utf-8")
    return create_full_pr(branch_name, file_path, title, body, base)


def _parse_remote_owner_repo() -> tuple[str, str]:
    """Extract owner and repo from the git remote origin URL."""
    r = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True, text=True,
    )
    url = r.stdout.strip()
    # Strip auth token: https://x-access-token:TOKEN@github.com/owner/repo
    if "@" in url:
        url = "https://" + url.split("@", 1)[1]
    # https://github.com/owner/repo.git or git@github.com:owner/repo.git
    for prefix in ["https://github.com/", "git@github.com:"]:
        if url.startswith(prefix):
            path = url[len(prefix):]
            if path.endswith(".git"):
                path = path[:-4]
            parts = path.split("/", 1)
            if len(parts) == 2:
                return parts[0], parts[1]
    raise RuntimeError(f"Cannot parse owner/repo from origin URL: {url}")


def create_full_pr(
    branch_name: str,
    files: str,
    title: str,
    body: str,
    base: str = "master",
) -> str:
    """Create a full PR: auth, branch, add, commit, push, open PR — all in one call."""
    lock = ".git/index.lock"
    if os.path.exists(lock):
        os.remove(lock)

    setup_git_auth(".")
    owner, repo = _parse_remote_owner_repo()

    def _git(args: str) -> str:
        r = subprocess.run(["git"] + shlex.split(args), capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or r.stdout.strip())
        return r.stdout.strip() or r.stderr.strip() or "(ok)"

    _git(f"checkout {base}")
    _git(f"checkout -B {branch_name}")

    for f in files.split():
        _git(f"add {f}")

    status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
    if not status:
        return f"No changes to commit. PR not created."

    _git(f'commit -m "{title}"')

    _git(f"push --force origin {branch_name}")

    result = create_pr(owner, repo, title, body, branch_name, base)
    pr_url = result.get("html_url", result.get("url", "unknown"))

    return f"PR created: {pr_url}"
