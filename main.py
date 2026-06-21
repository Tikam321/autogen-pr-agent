import asyncio
import os
import sys
from dotenv import load_dotenv
from autogen_agentchat.base import TaskResult
from workflow import team

load_dotenv()


def extract_pr_url(messages: list) -> str | None:
    for m in messages:
        content = str(getattr(m, "content", ""))
        if "PR created:" in content:
            return content.split("PR created:")[-1].strip()
    return None


async def run_workflow(issue: str) -> str | None:
    async for message in team.run_stream(task=issue):
        if isinstance(message, TaskResult):
            return extract_pr_url(message.messages)
    return None


async def main():
    if len(sys.argv) < 2:
        print("Usage: uv run python main.py <issue description>")
        print("   or: uv run python main.py < issue.txt")
        sys.exit(1)

    issue = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read().strip()

    repo_dir = os.getcwd()
    os.chdir(repo_dir)

    print(f"Issue: {issue}", file=sys.stderr)
    print(f"Repo:  {repo_dir}", file=sys.stderr)

    pr_url = await run_workflow(issue)

    if pr_url:
        print(pr_url)
    else:
        print("No PR was created", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
