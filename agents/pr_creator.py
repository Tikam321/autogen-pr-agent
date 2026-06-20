import os
import subprocess
import shlex
from autogen_agentchat.agents import AssistantAgent
from autogen_core.tools import FunctionTool
from config import get_model_client
from tools.git_tools import create_pr, setup_git_auth


def run_git(args: str) -> str:
    lock = os.path.join(".git", "index.lock")
    if os.path.exists(lock):
        os.remove(lock)
    result = subprocess.run(
        ["git"] + shlex.split(args),
        capture_output=True, text=True, cwd=".",
    )
    if result.returncode != 0:
        out = result.stdout.strip()
        err = result.stderr.strip()
        return f"Error (rc={result.returncode}): {err or out or 'unknown'}"
    out = result.stdout.strip()
    err = result.stderr.strip()
    return out or err or "(ok)"

pr_creator = AssistantAgent(
    "pr_creator",
    model_client=get_model_client(),
    reflect_on_tool_use=False,
    tools=[
        FunctionTool(run_git, description="Run a git command. Pass the arguments as a single string, e.g. 'checkout -b fix/issue'"),
        FunctionTool(create_pr, description="Create a GitHub pull request. Provide owner, repo, title, body, head branch, base branch (default: main)"),
        FunctionTool(setup_git_auth, description="Inject the GITHUB_TOKEN into the remote origin URL so git push works"),
    ],
    system_message=(
        "You create pull requests. Do the following steps:\n"
        "1. First call setup_git_auth(repo_dir='.') to inject the token into the remote URL.\n"
        "2. Create a new branch: run_git('checkout -b fix/add-function-bug')\n"
        "3. Stage: run_git('add calculator.py test_calculator.py')\n"
        "4. Commit: use run_git with a quoted message string, e.g. run_git('commit -m \"Fix add function bug: use + instead of -\"')\n"
        "5. Push: run_git('push origin fix/add-function-bug')\n"
        "6. Create a PR using: create_pr(owner='Tikam321', repo='test-calculator', title='...', body='...', head='fix/add-function-bug', base='master')\n"
        "7. When all steps complete successfully, end your response with 'PR_CREATED'."
    ),
)
