import os
import asyncio
import json
import re
from collections.abc import AsyncGenerator, Mapping, Sequence
from typing import Any, Literal, Optional, Union

from dotenv import load_dotenv
from openai import AsyncOpenAI, BadRequestError
from pydantic import BaseModel

from autogen_core import CancellationToken
from autogen_core.models import (
    ChatCompletionClient,
    CreateResult,
    FunctionExecutionResultMessage,
    LLMMessage,
    ModelInfo,
    RequestUsage,
    SystemMessage,
    UserMessage,
    AssistantMessage,
)
from autogen_core.tools import Tool, ToolSchema
from autogen_agentchat.agents._assistant_agent import FunctionCall

load_dotenv()

def _to_openai_messages(messages: Sequence[LLMMessage]) -> list[dict]:
    result: list[dict] = []
    for m in messages:
        if isinstance(m, SystemMessage):
            result.append({"role": "system", "content": m.content})
        elif isinstance(m, UserMessage):
            result.append({"role": "user", "content": m.content})
        elif isinstance(m, AssistantMessage):
            if isinstance(m.content, str):
                result.append({"role": "assistant", "content": m.content})
            elif isinstance(m.content, list) and m.content:
                fcs = m.content
                result.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": fc.id,
                            "type": "function",
                            "function": {"name": fc.name, "arguments": fc.arguments},
                        }
                        for fc in fcs
                    ],
                })
            else:
                result.append({"role": "assistant", "content": None})
        elif isinstance(m, FunctionExecutionResultMessage):
            for r in m.content:
                result.append({
                    "role": "tool",
                    "tool_call_id": r.call_id,
                    "content": r.content,
                })
        else:
            result.append({"role": "user", "content": str(m)})
    return result


def _openai_tools(tools: Sequence[Tool | ToolSchema]) -> list[dict]:
    out: list[dict] = []
    for t in tools:
        s: dict
        if isinstance(t, Tool):
            s = dict(t.schema)
        else:
            s = dict(t)
        s.pop("strict", None)
        params = s.get("parameters")
        if isinstance(params, dict):
            params.pop("additionalProperties", None)
        out.append({"type": "function", "function": s})
    return out


_FUNCTION_XML_RE = re.compile(
    r"<function=(\w+)>\s*(\{.*?\}|`[^`]+`)\s*</function>",
    re.DOTALL,
)


def _extract_xml_tool_calls(content: str) -> list[FunctionCall] | None:
    """Detect <function=name>args</function> patterns in text and return FunctionCall list."""
    matches = _FUNCTION_XML_RE.findall(content)
    if not matches:
        return None
    out: list[FunctionCall] = []
    for name, args in matches:
        args = args.strip()
        if args.startswith("`") and args.endswith("`"):
            args = args[1:-1]
        out.append(FunctionCall(id=name, arguments=args, name=name))
    return out


class RawGroqClient(ChatCompletionClient):
    """Uses the raw OpenAI async client — avoids AutoGen's tool-call XML issue."""

    def __init__(
        self,
        model: str = "llama-3.3-70b-versatile",
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._model = model
        key = api_key or os.getenv("OPEN_ROUTER_API_KEY") or os.getenv("GROQ_API_KEY")
        self._client = AsyncOpenAI(
            api_key=key,
            base_url=base_url or "https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": "https://github.com/Tikam321/pr-autogen-agent",
                "X-Title": "pr-autogen-agent",
            },
        )
        self._mi: ModelInfo = {
            "vision": False,
            "function_calling": True,
            "json_output": True,
            "structured_output": False,
            "family": "unknown",
        }
        self._total_usage = RequestUsage(prompt_tokens=0, completion_tokens=0)
        self._actual_usage = RequestUsage(prompt_tokens=0, completion_tokens=0)

    async def create(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Tool | ToolSchema] = [],
        tool_choice: Tool | Literal["auto", "required", "none"] = "auto",
        json_output: Optional[bool | type[BaseModel]] = None,
        extra_create_args: Mapping[str, Any] = {},
        cancellation_token: Optional[CancellationToken] = None,
    ) -> CreateResult:
        oai_messages = _to_openai_messages(messages)
        oai_tools = _openai_tools(tools) if tools else None
        tc: str | Literal["auto", "required", "none"] = "auto"
        if isinstance(tool_choice, Tool):
            tc = tool_choice.name  # type: ignore[assignment]
        else:
            tc = tool_choice

        kwargs: dict[str, Any] = dict(extra_create_args)
        kwargs.setdefault("model", self._model)
        kwargs.setdefault("max_tokens", 4096)
        if json_output:
            kwargs["response_format"] = {"type": "json_object"}

        for attempt in range(3):
            try:
                create_kwargs: dict[str, Any] = dict(kwargs)
                create_kwargs["model"] = create_kwargs.pop("model", self._model)
                create_kwargs["messages"] = oai_messages
                create_kwargs["stream"] = False
                if oai_tools:
                    create_kwargs["tools"] = oai_tools
                if tc != "auto":
                    create_kwargs["tool_choice"] = tc
                resp = await self._client.chat.completions.create(
                    **create_kwargs,
                )
                break
            except BadRequestError as e:
                body = getattr(e, "body", {}) or {}
                if isinstance(body, dict) and body.get("code") == "tool_use_failed":
                    print(f"  [raw retry] tool_use_failed (attempt {attempt+1}/3)")
                    await asyncio.sleep(1)
                    continue
                raise
        else:
            raise e  # type: ignore[name-defined]

        choice = resp.choices[0]
        msg = choice.message

        content: str | list = ""

        if msg.tool_calls:
            content = [
                FunctionCall(id=t.id, arguments=t.function.arguments, name=t.function.name)
                for t in msg.tool_calls
            ]
        else:
            raw = msg.content
            if raw is None:
                raw = ""
            if isinstance(raw, list):
                texts: list[str] = []
                for part in raw:
                    if isinstance(part, dict):
                        texts.append(part.get("text", json.dumps(part)))
                    else:
                        texts.append(str(part))
                raw = " ".join(texts)
            else:
                raw = str(raw)
            if not raw.strip():
                raw = "(no response)"
            if oai_tools and (xml_calls := _extract_xml_tool_calls(raw)):
                content = xml_calls
            else:
                content = raw

        usage = RequestUsage(
            prompt_tokens=getattr(resp.usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(resp.usage, "completion_tokens", 0) or 0,
        )
        self._total_usage = RequestUsage(
            prompt_tokens=self._total_usage.prompt_tokens + usage.prompt_tokens,
            completion_tokens=self._total_usage.completion_tokens + usage.completion_tokens,
        )
        self._actual_usage = usage

        fr = choice.finish_reason or "stop"
        if fr in ("tool_calls", "function_call") or isinstance(content, list):
            fr = "function_calls"
        return CreateResult(
            content=content,
            usage=usage,
            finish_reason=fr,
            cached=False,
            thought=getattr(msg, "reasoning_content", None) if hasattr(msg, "reasoning_content") else None,
        )

    def create_stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Tool | ToolSchema] = [],
        tool_choice: Tool | Literal["auto", "required", "none"] = "auto",
        json_output: Optional[bool | type[BaseModel]] = None,
        extra_create_args: Mapping[str, Any] = {},
        cancellation_token: Optional[CancellationToken] = None,
    ) -> AsyncGenerator[Union[str, CreateResult], None]:
        raise NotImplementedError("Streaming not supported")

    async def close(self) -> None:
        await self._client.close()

    def actual_usage(self) -> RequestUsage:
        return self._actual_usage

    def total_usage(self) -> RequestUsage:
        return self._total_usage

    def count_tokens(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Tool | ToolSchema] = [],
    ) -> int:
        text = " ".join(
            m.content if isinstance(m.content, str) else ""
            for m in messages
        )
        return len(text.split())

    def remaining_tokens(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Tool | ToolSchema] = [],
    ) -> int:
        return 128_000 - self.count_tokens(messages)

    @property
    def capabilities(self) -> ModelInfo:
        return self._mi

    @property
    def model_info(self) -> ModelInfo:
        return self._mi

groq = RawGroqClient(
    model="llama-3.3-70b-versatile",
    base_url="https://api.groq.com/openai/v1",
    api_key=os.getenv("GROQ_API_KEY"),
)

openRouter = RawGroqClient(
        model="google/gemma-4-31b-it:free",
        api_key=os.getenv("OPEN_ROUTER_API_KEY"),
        base_url="https://openrouter.ai/api/v1",
)

nvidia = RawGroqClient(
    model="deepseek-ai/deepseek-v4-flash",
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.environ.get("NVIDIA_API_KEY"),
)

deepseek = RawGroqClient(
    model="deepseek-v4-flash",
    base_url="https://api.deepseek.com",
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
)

mistral_client = RawGroqClient(
    model="mistral-medium",  # or "mistral-large", "mistral-small", etc.
    api_key=os.getenv("MISTRAL_API_KEY"),
    base_url="https://api.mistral.ai/v1/",
)

llm = RawGroqClient(
    model="gemini-3.1-pro-preview",
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    api_key=os.environ.get("GOOGLE_API_KEY")
)


def get_model_client() -> ChatCompletionClient:
    return mistral_client
