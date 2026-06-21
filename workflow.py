from autogen_agentchat.teams import GraphFlow, DiGraph, DiGraphNode, DiGraphEdge
from autogen_agentchat.conditions import TextMentionTermination, MaxMessageTermination
from agents.explorer import explorer
from agents.planner import planner
from agents.executor import executor


nodes = {
    "explorer": DiGraphNode(name="explorer", edges=[DiGraphEdge(target="planner")]),
    "planner": DiGraphNode(name="planner", edges=[DiGraphEdge(target="executor")]),
    "executor": DiGraphNode(name="executor", edges=[]),
}

graph = DiGraph(nodes=nodes, default_start_node="explorer")

termination = TextMentionTermination("PR_CREATED") | MaxMessageTermination(20)

team = GraphFlow(
    participants=[explorer, planner, executor],
    graph=graph,
    termination_condition=termination,
)
