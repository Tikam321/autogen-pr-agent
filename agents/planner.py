from autogen_agentchat.agents import AssistantAgent
from config import get_model_client

planner = AssistantAgent(
    "planner",
    model_client=get_model_client(),
    tools=[],
    system_message=(
        "You are a senior software engineer. Based on the exploration findings below, "
        "create a detailed step-by-step plan to fix the issue. "
        "Each step should specify the file and the exact change needed.\n"
        "IMPORTANT: You do NOT have access to any tools. Do NOT call read_file, write_file, edit_file, "
        "or any other function. Only output a plain text plan."
    ),
)
