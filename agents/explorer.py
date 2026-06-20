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
        "You are a codebase explorer. Given an issue description, do the following:\n"
        "1. First, call list_directory on './' to see what files exist.\n"
        "2. For each relevant file found, call read_file to get its contents.\n"
        "3. If you need to find specific patterns, use grep_search.\n"
        "4. Summarize your findings concisely, including full file paths and the relevant code.\n"
        "Do NOT stop after listing the directory — you MUST read the actual file contents."
    ),
)
