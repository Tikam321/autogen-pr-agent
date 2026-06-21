from autogen_agentchat.agents import AssistantAgent
from config import get_model_client
from tools.file_tools import read_file, grep_search, list_directory
from autogen_core.tools import FunctionTool

explorer = AssistantAgent(
    "explorer",
    model_client=get_model_client(),
    reflect_on_tool_use=False,
    tools=[
        FunctionTool(read_file, description="Read a file from the local filesystem and return its contents"),
        FunctionTool(grep_search, description="Search for a regex pattern in files under a directory"),
        FunctionTool(list_directory, description="List files and directories in a given path"),
    ],
    system_message=(
        "You are a codebase explorer. You MUST call these tools in order:\n"
        "1. list_directory(path='./')\n"
        "2. read_file(path='calculator.py')\n"
        "3. read_file(path='test_calculator.py')\n"
        "After reading the files, output their COMPLETE contents. "
        "Do NOT stop after listing the directory. You MUST read the files."
    ),
)
