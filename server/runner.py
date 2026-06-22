import os
import logging
from autogen_agentchat.base import TaskResult
from workflow import team

logger = logging.getLogger(__name__)


def _extract_pr_url(messages: list) -> str | None:
    for m in messages:
        content = str(getattr(m, "content", ""))
        if "PR created:" in content:
            return content.split("PR created:")[-1].strip()
    return None


async def run_agent(repo_dir: str, issue_text: str) -> str:
    original_cwd = os.getcwd()
    os.chdir(repo_dir)

    try:
        logger.info("Running agent in %s", repo_dir)
        async for message in team.run_stream(task=issue_text):
            if isinstance(message, TaskResult):
                pr_url = _extract_pr_url(message.messages)
                if pr_url:
                    logger.info("PR URL extracted: %s", pr_url)
                    return pr_url
        logger.warning("Agent finished but no PR URL found in output")
        raise RuntimeError("Agent finished without creating a PR")
    finally:
        os.chdir(original_cwd)
