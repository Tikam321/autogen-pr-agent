from autogen_agentchat.agents import AssistantAgent
from config import get_model_client
from tools.file_tools import read_file, write_file, edit_file
from autogen_core.tools import FunctionTool

fixer = AssistantAgent(
    "fixer",
    model_client=get_model_client(),
    reflect_on_tool_use=False,
    tools=[
        FunctionTool(read_file, description="Read a file from the local filesystem and return its contents"),
        FunctionTool(write_file, description="Write content to a file, overwriting if it exists"),
        FunctionTool(edit_file, description="Find and replace the first occurrence of a string in a file"),
    ],
    system_message=(
        "You are an implementer. Follow the plan and apply the changes.\n"
        "You MUST use the available tools to read and modify files. "
        "Do NOT write raw Python code (no open(), no with open as file, etc). "
        "Always call read_file first, then use edit_file or write_file to make changes."
    ),
)
