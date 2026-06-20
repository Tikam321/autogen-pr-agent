import asyncio
import os
import sys
from dotenv import load_dotenv

load_dotenv()

TEST_REPO = "/private/var/folders/jd/bm1_qs2d6qng6brmj0b44s8c0000gn/T/opencode/test-repo"

from autogen_agentchat.base import TaskResult
from workflow import team


def reset_repo():
    import subprocess
    lock = os.path.join(TEST_REPO, ".git", "index.lock")
    if os.path.exists(lock):
        os.remove(lock)
    subprocess.run(
        ["git", "checkout", "master"],
        capture_output=True, cwd=TEST_REPO,
    )
    subprocess.run(
        ["git", "reset", "--hard", "origin/master"],
        capture_output=True, cwd=TEST_REPO,
    )
    subprocess.run(
        ["git", "branch", "-D", "fix/add-function-bug"],
        capture_output=True, cwd=TEST_REPO,
    )


async def run_workflow(issue: str) -> int:
    msg_count = 0

    STAGE_NAMES = {
        "user": "USER INPUT",
        "explorer": "STEP 1: EXPLORER",
        "planner": "STEP 2: PLANNER",
        "fixer": "STEP 3: FIXER",
        "reviewer": "STEP 4: REVIEWER",
        "pr_creator": "STEP 5: PR CREATOR",
    }

    seen_stages = set()

    async for message in team.run_stream(task=issue):
        msg_count += 1
        source = getattr(message, "source", "?")
        msg_type = type(message).__name__

        if source in STAGE_NAMES and source not in seen_stages:
            seen_stages.add(source)
            print()
            print("=" * 70)
            print(f"  {STAGE_NAMES[source]}")
            print("=" * 70)

        if isinstance(message, TaskResult):
            print()
            print("=" * 70)
            print("  RESULT")
            print("=" * 70)
            print(f"  Total inner messages: {len(message.messages)}")
            agent_msgs = [m for m in message.messages if hasattr(m, "source") and m.source not in ("user",)]
            print(f"  Agent messages: {len(agent_msgs)}")
            for m in agent_msgs:
                s = getattr(m, "source", "?")
                c = str(getattr(m, "content", str(m)))[:120]
                print(f"    [{s}]: {c}")
            continue

        content = str(getattr(message, "content", str(message)))

        if msg_type == "ThoughtEvent":
            print(f"    [thinking] {content[:200]}")
        elif msg_type == "ToolCallRequestEvent":
            fcs = getattr(message, "content", [])
            if isinstance(fcs, list):
                for fc in fcs:
                    print(f"    [tool] {fc.name}({fc.arguments})")
        elif msg_type == "ToolCallExecutionEvent":
            results = getattr(message, "content", [])
            if isinstance(results, list):
                for r in results:
                    is_err = getattr(r, "is_error", False)
                    tag = "error" if is_err else "ok"
                    c = str(getattr(r, "content", ""))[:150]
                    print(f"    [{tag}] {c}")
        elif msg_type == "ToolCallSummaryMessage":
            print(f"    [result] {content[:200]}")
        elif msg_type == "TextMessage":
            print(f"    {content[:300]}")

    return msg_count


async def main():
    issue = (
        "The add function in calculator.py returns wrong results. "
        "When I call add(2, 3), it returns -1 instead of 5. "
        "The problem is that it subtracts instead of adding. "
        "Fix the bug and make sure the tests pass."
    )

    print("=" * 70)
    print("ISSUE:", issue)
    print("WORK DIR:", TEST_REPO)
    print("=" * 70)

    os.chdir(TEST_REPO)

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        if attempt > 1:
            print(f"\n{'='*70}")
            print(f"  RETRY ATTEMPT {attempt}/{max_retries}")
            print(f"{'='*70}")
            reset_repo()
            os.chdir(TEST_REPO)

        try:
            msg_count = await run_workflow(issue)
            print()
            print("=" * 70)
            print(f"  WORKFLOW COMPLETE (attempt {attempt})")
            print(f"  Total stream messages: {msg_count}")
            print("=" * 70)
            return
        except RuntimeError as e:
            print(f"\n  ERROR on attempt {attempt}: {str(e)[:200]}")
            if attempt < max_retries:
                print("  Retrying...")
            else:
                print("  All retries exhausted.")
                raise


if __name__ == "__main__":
    asyncio.run(main())
