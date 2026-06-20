# pr-autogen-agent

Single Python project. Python 3.14. No commits yet. Managed by `uv`.

## Commands

```bash
uv sync              # sync lockfile
uv add <pkg>         # add dependency
uv run python <file> # run script in venv
```

## Key dependencies

- `autogen-agentchat>=0.7.5` — agent framework
- `autogen-ext[openai]` — LLM client for OpenAI-compatible APIs (Groq)
- `dotenv` (not `python-dotenv`) — import as `from dotenv import load_dotenv`

## LLM provider: Groq

- `base_url="https://api.groq.com/openai/v1"`, model `llama-3.3-70b-versatile`
- `OpenAIChatCompletionClient` requires explicit `model_info` dict:
  `{"vision": False, "function_calling": True, "json_output": True, "structured_output": False, "family": "unknown"}`
- API keys in `.env`: `GROQ_API_KEY`, `GOOGLE_API_KEY`, `NVIDIA_API_KEY`
- Shared client factory: `config.get_model_client()`
- Template: `.env.example` lists required vars

## Agent conventions (from working POC in `app.py`)

- `tools` goes on `AssistantAgent`, **not** on `OpenAIChatCompletionClient` — passing tools to the model client puts them in `create_args` and causes `TypeError: got multiple values for keyword argument 'tools'`
- Multi-task input: `task=[TextMessage(content="...", source="user"), ...]` (not raw strings)
- Streaming: `async for message in agent.run_stream(...)` → check `isinstance(message, TaskResult)` for final result
- `FunctionTool` wrappers register on the agent via `tools=[...]`

## Project structure

```
pr-autogen-agent/
├── agents/           # AutoGen agent definitions (empty stubs)
├── tools/            # FunctionTool wrappers (empty stubs)
├── server/           # Webhook server (empty stubs)
├── docs/             # architecture.md, implementation-plan.md
├── config.py         # get_model_client() factory
├── app.py            # Learning POC
└── main.py           # Placeholder
```

## Architecture reference

- `docs/architecture.md` — design for a 6-agent `GraphFlow` PR automation system
- `docs/implementation-plan.md` — 17-step build plan

## Gotchas

- `.env` is in `.gitignore` — but still contains live API keys; do not commit
- `.env` also covers `__pycache__/`, `*.py[oc]`, `build/`, `dist/`, `wheels/`, `*.egg-info`, `.venv`
