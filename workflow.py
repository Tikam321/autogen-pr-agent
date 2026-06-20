from autogen_agentchat.teams import GraphFlow, DiGraph, DiGraphNode, DiGraphEdge
from autogen_agentchat.conditions import TextMentionTermination, MaxMessageTermination
from autogen_agentchat.messages import BaseChatMessage

from agents.explorer import explorer
from agents.planner import planner
from agents.fixer import fixer
from agents.reviewer import reviewer
from agents.pr_creator import pr_creator


def needs_fix(message: BaseChatMessage) -> bool:
    return "APPROVED" not in message.to_model_text()


nodes = {
    "explorer": DiGraphNode(name="explorer", edges=[DiGraphEdge(target="planner")]),
    "planner": DiGraphNode(name="planner", edges=[DiGraphEdge(target="fixer", activation_group="forward")]),
    "fixer": DiGraphNode(name="fixer", edges=[DiGraphEdge(target="reviewer")]),
    "reviewer": DiGraphNode(
        name="reviewer",
        edges=[
            DiGraphEdge(target="pr_creator", condition="APPROVED"),
            DiGraphEdge(target="fixer", condition=needs_fix, activation_group="backward"),
        ],
    ),
    "pr_creator": DiGraphNode(name="pr_creator", edges=[]),
}

graph = DiGraph(nodes=nodes, default_start_node="explorer")

termination = TextMentionTermination("PR_CREATED") | MaxMessageTermination(20)

team = GraphFlow(
    participants=[explorer, planner, fixer, reviewer, pr_creator],
    graph=graph,
    termination_condition=termination,
)
