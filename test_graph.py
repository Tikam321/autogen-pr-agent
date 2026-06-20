"""Test: agent_c has 2 incoming edges with different activation groups."""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from autogen_agentchat.teams import GraphFlow, DiGraph, DiGraphNode, DiGraphEdge
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_agentchat.base import TaskResult
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import BaseChatMessage
from config import get_model_client

TEST_REPO = "/private/var/folders/jd/bm1_qs2d6qng6brmj0b44s8c0000gn/T/opencode/test-repo"

model_client = get_model_client()

agent_a = AssistantAgent(
    name="agent_a",
    model_client=model_client,
    system_message="You are A. Respond with 'GOING_TO_B' then stop.",
)
agent_b = AssistantAgent(
    name="agent_b",
    model_client=model_client,
    system_message="You are B. Respond with 'GOING_TO_C' then stop.",
)
agent_c = AssistantAgent(
    name="agent_c",
    model_client=model_client,
    system_message="You are C. Respond with 'GOING_TO_D' then stop.",
)
agent_d = AssistantAgent(
    name="agent_d",
    model_client=model_client,
    system_message="You are D. If the last message says 'GOING_TO_D', respond with 'APPROVED'. Otherwise respond with 'GOING_TO_C'.",
)
agent_e = AssistantAgent(
    name="agent_e",
    model_client=model_client,
    system_message="You are E. Just respond with 'DONE'.",
)


def needs_fix(message: BaseChatMessage) -> bool:
    return "APPROVED" not in message.to_model_text()


# Key: use different activation_groups for the two incoming edges to agent_c
nodes = {
    "agent_a": DiGraphNode(name="agent_a", edges=[DiGraphEdge(target="agent_b")]),
    "agent_b": DiGraphNode(name="agent_b", edges=[DiGraphEdge(target="agent_c", activation_group="forward")]),
    "agent_c": DiGraphNode(name="agent_c", edges=[DiGraphEdge(target="agent_d")]),
    "agent_d": DiGraphNode(
        name="agent_d",
        activation="any",
        edges=[
            DiGraphEdge(target="agent_e", condition="APPROVED"),
            DiGraphEdge(target="agent_c", condition=needs_fix, activation_group="backward"),
        ],
    ),
    "agent_e": DiGraphNode(name="agent_e", edges=[]),
}

graph = DiGraph(nodes=nodes, default_start_node="agent_a")
termination = MaxMessageTermination(10)

team = GraphFlow(
    participants=[agent_a, agent_b, agent_c, agent_d, agent_e],
    graph=graph,
    termination_condition=termination,
)


async def main():
    os.chdir(TEST_REPO)
    msg_count = 0
    async for message in team.run_stream(task="Start"):
        msg_count += 1
        t = type(message).__name__
        s = getattr(message, "source", "?")
        c = str(getattr(message, "content", str(message)))[:300]
        print(f"#{msg_count} [{t}] <{s}>: {c}")
        if isinstance(message, TaskResult):
            print(f"  >> Inner msgs: {len(message.messages)}")
    print(f"Total: {msg_count}")


asyncio.run(main())
