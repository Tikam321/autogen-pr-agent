from autogen_agentchat.agents import AssistantAgent
from autogen_core.tools import FunctionTool
from config import get_model_client
from tools.git_tools import fix_and_create_pr


executor = AssistantAgent(
    "executor",
    model_client=get_model_client(),
    reflect_on_tool_use=False,
    tools=[
        FunctionTool(fix_and_create_pr, description="Fix a bug in a file and create a PR. Parameters: file_path, search_text (substring to find), replace_with (text to replace it with), branch_name, title, body, base (default: master)"),
    ],
    system_message=(
        "You are a developer. Call fix_and_create_pr with the correct arguments "
        "to fix the bug and create a pull request. "
        "End with 'PR_CREATED' when done."
    ),
)
