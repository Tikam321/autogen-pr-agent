from autogen_agentchat.agents import AssistantAgent
from config import get_model_client
from tools.file_tools import read_file
from autogen_core.tools import FunctionTool

reviewer = AssistantAgent(
    "reviewer",
    model_client=get_model_client(),
    reflect_on_tool_use=False,
    tools=[
        FunctionTool(read_file, description="Read a file from the local filesystem and return its contents"),
    ],
    system_message=(
        "You are a senior code reviewer. Review the changes for correctness, "
        "missing edge cases, code style, breaking changes, and test coverage.\n"
        "Read the fixed file with read_file, then analyze whether the fix is correct.\n"
        "If everything looks good, end your response with 'APPROVED'. "
        "Otherwise, explain what needs to be fixed."
    ),
)
