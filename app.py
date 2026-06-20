# pip install -U "autogen-agentchat" "autogen-ext[openai]"
# %%
import asyncio
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.base import TaskResult
from autogen_ext.models.openai import OpenAIChatCompletionClient
import os 
from autogen_agentchat.messages import TextMessage
from dotenv import load_dotenv
load_dotenv()


def weatherTool(city: str):
    """this is weather tool which is helping to  show the weather update for evry ctity also append  jokse so that user can be happy in the response"""
    return f"the current weather for the city {city} is 25 degree ceclius thank you for asking"

system_prompt = """
return the tool response and also append the simple jockes to user so that he can be ahppy after knowing the eather update
if the tools is not used then you can give the response according to your knowledge
"""

async def main() -> None:
    agent = AssistantAgent(name="assistant", model_client=OpenAIChatCompletionClient(
    model="llama-3.3-70b-versatile",
    base_url="https://api.groq.com/openai/v1",
    api_key=os.getenv("GROQ_API_KEY"),
     model_info={
            "vision": False,
            "function_calling": True,
            "json_output": True,
            "structured_output": False,
            "family": "unknown",
        },
      
        )
          
            ,system_message=system_prompt)
    
    
    async for message in agent.run_stream(task=[
        TextMessage(content="how the weather in mumbai today", source="user"),
        TextMessage(content="who is number one footballer", source="user"),
    ]):
        # print(f"message {message}")
        if isinstance(message, TaskResult):
            print(f"message123: {message.messages[-1].content}")

asyncio.run(main())

# %%
