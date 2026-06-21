# Multi-Agent Orchestration Patterns in AutoGen 0.7.x

AutoGen provides several ways to orchestrate multiple agents. This document explains each pattern, when to use it, and how they compare.

## 1. GraphFlow (Directed Graph)

**File**: `autogen_agentchat.teams.GraphFlow`
**Used in this project**: Yes

```python
from autogen_agentchat.teams import GraphFlow, DiGraph, DiGraphNode, DiGraphEdge
from autogen_agentchat.conditions import TextMentionTermination, MaxMessageTermination

graph = DiGraph(nodes={
    "explorer": DiGraphNode(edges=[DiGraphEdge(target="planner")]),
    "planner": DiGraphNode(edges=[DiGraphEdge(target="fixer")]),
    "fixer": DiGraphNode(edges=[DiGraphEdge(target="reviewer")]),
    "reviewer": DiGraphNode(edges=[
        DiGraphEdge(target="pr_creator", condition="APPROVED"),
        DiGraphEdge(target="fixer", condition=needs_fix, activation_group="backward"),
    ]),
    "pr_creator": DiGraphNode(edges=[]),
}, default_start_node="explorer")

team = GraphFlow(
    participants=[explorer, planner, fixer, reviewer, pr_creator],
    graph=graph,
    termination_condition=TextMentionTermination("PR_CREATED") | MaxMessageTermination(20),
)
```

### Key Concepts

| Concept | Description |
|---|---|
| **DiGraphNode** | A node in the graph, wraps an Agent. Has a name and outgoing edges. |
| **DiGraphEdge** | A directed connection between nodes. Can have a `condition` and `activation_group`. |
| **Edge condition** | Either a string (`"APPROVED"`) — routes if the string is in the message text — or a callable `(message: BaseChatMessage) -> bool`. |
| **Activation group** | Prevents the same agent from being activated by multiple input paths in the same cycle. Nodes with multiple incoming edges should use distinct group names. |
| **termination_condition** | Combined with `\|` (OR). Stops when ANY condition is met. |

### When to Use

- Complex workflows with branching and loops
- Conditional routing based on agent output (approval gates, retry loops)
- Predictable, debuggable execution order
- **Not good for**: Open-ended conversations where the next speaker varies dynamically

---

## 2. RoundRobinGroupChat

**File**: `autogen_agentchat.teams.RoundRobinGroupChat`

```python
from autogen_agentchat.teams import RoundRobinGroupChat

team = RoundRobinGroupChat(
    participants=[explorer, planner, fixer, reviewer, pr_creator],
    termination_condition=TextMentionTermination("PR_CREATED") | MaxMessageTermination(20),
)
```

### How it Works

Agents speak in **fixed circular order**: Agent A → Agent B → Agent C → Agent A → Agent B → ...

- Every agent gets a turn in sequence, regardless of what the previous agent said
- The order is determined by the `participants` list
- An agent cannot skip its turn, and no agent speaks twice before others

### Key Differences from GraphFlow

| Aspect | GraphFlow | RoundRobin |
|---|---|---|
| **Routing** | Conditional edges determine next agent | Fixed circular sequence |
| **Loops** | Allowed via conditional edges | Automatic (circular by nature) |
| **Flexibility** | High — custom conditions per edge | Low — every agent always speaks |
| **Setup complexity** | Medium — must define graph | Low — just list participants |

### When to Use

- Collaborative discussions where all agents should contribute
- Brainstorming sessions
- Simple linear pipelines
- **Not good for**: Approval gates, branching logic, or workflows with conditional loops

---

## 3. SelectorGroupChat

**File**: `autogen_agentchat.teams.SelectorGroupChat`

```python
from autogen_agentchat.teams import SelectorGroupChat

team = SelectorGroupChat(
    participants=[agent1, agent2, agent3],
    model_client=selector_llm,  # The LLM that picks the next speaker
    termination_condition=TextMentionTermination("DONE"),
)
```

### How it Works

An LLM-based **selector** reads the conversation history and decides which agent should speak next.

```python
selector_prompt = "Based on the conversation, select the next speaker from: {roles}"
```

- The selector receives the full conversation history plus a prompt
- It outputs the name of the agent that should speak next
- The selected agent then generates its response
- This repeats until termination

### Key Differences

| Aspect | GraphFlow | SelectorGroupChat |
|---|---|---|
| **Next speaker** | Predefined edges determine it | LLM chooses dynamically |
| **Predictability** | High — deterministic routing | Low — depends on LLM choice |
| **Flexibility** | Limited to defined edges | Unlimited — any agent can speak anytime |
| **Overhead** | None for routing | Extra LLM call per turn (selector cost) |
| **Debugging** | Easy — trace the graph path | Hard — LLM decision is opaque |

### When to Use

- Open-ended conversations (e.g., customer support, debate, panel discussion)
- When the next speaker depends on the content of previous messages
- Dynamic team formation
- **Not good for**: Strict pipelines, deterministic workflows, approval gates

---

## 4. Swarm (Hand-off Pattern)

**File**: `autogen_agentchat.teams.Swarm` (AutoGen 0.4.x / experimental)

```python
from autogen_agentchat.teams import Swarm

# Agents can hand off to each other via function calls
def handoff_to_reviewer() -> str:
    """Hand off the conversation to the reviewer agent."""
    return "REVIEWER"

team = Swarm(
    participants=[fixer, reviewer],
    termination_condition=TextMentionTermination("APPROVED"),
)
```

### How it Works

Agents can **hand off** the conversation to other agents by returning a special message or calling a handoff function. This creates a dynamic, agent-driven flow:

1. Agent A is speaking
2. Agent A decides to invoke a handoff (e.g., "I need a review")
3. The runtime routes to Agent B
4. Agent B can hand off back to A or to another agent

### Key Differences

| Aspect | GraphFlow | Swarm |
|---|---|---|
| **Who controls routing** | The graph definition | The agents themselves |
| **Predictability** | High | Low — agent-driven |
| **Flexibility** | Static edges | Dynamic hand-offs |
| **Complexity** | Medium | High — hard to debug |
| **When to use** | Fixed workflows | Dynamic team collaboration |

### When to Use

- Teams where agents discover each other at runtime
- Highly dynamic conversations
- **Not good for**: Simple pipelines, deterministic workflows

---

## 5. SequentialRoutedAgent (Low-Level)

**File**: `autogen_agentchat.teams._group_chat._sequential_routed_agent`

This is an internal class used by GraphFlow and GroupChats. It handles the message-passing bus between agents. You generally don't use this directly.

---

## Comparison Table

| Pattern | Routing Mechanism | Loops | Conditional | LLM Overhead | Predictability | Best For |
|---|---|---|---|---|---|---|
| **GraphFlow** | Static directed graph with condition edges | ✅ via cyclic edges | ✅ string match / callable | None (static) | High | Approval gates, retry loops, pipelines |
| **RoundRobin** | Fixed circular order | ✅ automatic | ❌ | None | Very High | Simple sequential tasks, discussions |
| **SelectorGroupChat** | LLM chooses next speaker | ✅ possible | ✅ LLM-driven | Extra LLM call per turn | Low | Open-ended conversations, dynamic teams |
| **Swarm** | Agent-driven hand-offs | ✅ via hand-offs | ✅ per-handoff | None (agent decides) | Very Low | Dynamic team collaboration, discovery |
| **SequentialRoutedAgent** | Fixed message bus | ❌ | ❌ | None | Very High | Internal — not used directly |

---

## Choosing a Pattern for Your Use Case

```
Do you need conditional branching (if/else)?
├── Yes → GraphFlow
└── No → Is the conversation open-ended?
    ├── Yes → SelectorGroupChat or Swarm
    └── No → RoundRobinGroupChat
```

### Examples

| Use Case | Pattern |
|---|---|
| PR Agent (explore → plan → fix → review → PR) with approval gate | **GraphFlow** |
| Three agents debating a topic | **SelectorGroupChat** or **RoundRobin** |
| Customer support (triage agent → specialist → resolution) | **SelectorGroupChat** |
| Data pipeline (fetch → process → save) | **RoundRobin** or **GraphFlow** |
| Code review bot (fix → review → fix → review → merge) | **GraphFlow** (loop) |
| Collaborative writing (outline → draft → edit → finalize) | **RoundRobin** |
| Multi-step research (search → read → summarize → fact-check) | **GraphFlow** |

---

## Termination Conditions

All patterns support combining termination conditions with the `|` operator:

```python
from autogen_agentchat.conditions import TextMentionTermination, MaxMessageTermination

# Stop when either condition is met
termination = TextMentionTermination("DONE") | MaxMessageTermination(20)

# Stop when ALL conditions are met (use &)
termination = TextMentionTermination("DONE") & MaxMessageTermination(10)
```

| Condition | Description |
|---|---|
| `TextMentionTermination("text")` | Stops when any message contains the text |
| `MaxMessageTermination(n)` | Stops after n total messages |
| `ExternalTermination()` | Manual stop via API |
| `TimeCondition(seconds)` | Stops after elapsed time |
