import hashlib
import json
import math
import re
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, RateLimitError

# USD per 1M tokens (input, output); unknown models are tracked with zero cost and flagged
MODEL_PRICING: dict[str, tuple[Decimal, Decimal]] = {
    "gpt-4o-mini": (Decimal("0.15"), Decimal("0.60")),
    "gpt-4o": (Decimal("2.50"), Decimal("10.00")),
    "gpt-4.1": (Decimal("2.00"), Decimal("8.00")),
    "gpt-4.1-mini": (Decimal("0.40"), Decimal("1.60")),
    "gpt-4.1-nano": (Decimal("0.10"), Decimal("0.40")),
    "gpt-5": (Decimal("1.25"), Decimal("10.00")),
    "gpt-5-mini": (Decimal("0.25"), Decimal("2.00")),
    "gpt-5-nano": (Decimal("0.05"), Decimal("0.40")),
    "text-embedding-3-small": (Decimal("0.02"), Decimal("0")),
    "text-embedding-3-large": (Decimal("0.13"), Decimal("0")),
}
MOCK_PROVIDER = "mock"
LOCAL_EMBEDDING_MODEL = "local-hash-1536"


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    input_price, output_price = MODEL_PRICING.get(model, (Decimal("0"), Decimal("0")))
    return (input_price * input_tokens + output_price * output_tokens) / Decimal(1_000_000)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMMessage:
    role: str
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall]
    input_tokens: int
    output_tokens: int
    model: str
    provider: str
    latency_ms: int = 0


# Error kinds drive intentional fallbacks instead of accidental exception paths
MODEL_UNAVAILABLE = "model_unavailable"
RATE_LIMITED = "rate_limited"
TRANSIENT = "transient"
AUTH = "auth"
INVALID_REQUEST = "invalid_request"
DEFAULT_MAX_OUTPUT_TOKENS = 4096
REASONING_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")


class LLMError(Exception):
    def __init__(self, message: str, recoverable: bool, kind: str = INVALID_REQUEST) -> None:
        super().__init__(message)
        self.recoverable = recoverable
        self.kind = kind


class LLMProvider(Protocol):
    name: str
    is_mock: bool

    async def complete(
        self,
        *,
        model: str,
        messages: list[LLMMessage],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.3,
        json_mode: bool = False,
        purpose: str = "general",
        hints: dict[str, Any] | None = None,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> LLMResponse: ...

    async def embed(self, texts: list[str], model: str) -> tuple[list[list[float]], int]: ...


def _to_openai_message(message: LLMMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
            }
            for call in message.tool_calls
        ]
    if message.tool_call_id:
        payload["tool_call_id"] = message.tool_call_id
    return payload


class OpenAICompatibleProvider:
    is_mock = False

    def __init__(self, *, api_key: str, base_url: str, name: str = "openai_compatible") -> None:
        self.name = name
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=180, max_retries=2)

    async def complete(
        self,
        *,
        model: str,
        messages: list[LLMMessage],
        tools: list[ToolSpec] | None = None,
        temperature: float = 0.3,
        json_mode: bool = False,
        purpose: str = "general",
        hints: dict[str, Any] | None = None,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> LLMResponse:
        request: dict[str, Any] = {
            "model": model,
            "messages": [_to_openai_message(message) for message in messages],
            # Hard output cap: bounds cost and makes budget reservations an upper bound
            "max_completion_tokens": max_output_tokens,
        }
        if not model.startswith(REASONING_MODEL_PREFIXES):
            # Reasoning models only accept their default temperature
            request["temperature"] = temperature
        if tools:
            request["tools"] = [
                {
                    "type": "function",
                    "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
                }
                for t in tools
            ]
        if json_mode:
            request["response_format"] = {"type": "json_object"}
        started = time.monotonic()
        try:
            response = await self._client.chat.completions.create(**request)
        except Exception as error:
            raise classify_error(error) from error
        choice = response.choices[0].message
        tool_calls = []
        for call in choice.tool_calls or []:
            function = getattr(call, "function", None)
            if function is None:
                continue
            try:
                arguments = json.loads(function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {"_invalid_json": function.arguments}
            tool_calls.append(ToolCall(id=call.id, name=function.name, arguments=arguments))
        usage = response.usage
        return LLMResponse(
            content=choice.content,
            tool_calls=tool_calls,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            model=model,
            provider=self.name,
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    async def embed(self, texts: list[str], model: str) -> tuple[list[list[float]], int]:
        if model == LOCAL_EMBEDDING_MODEL:
            return local_embeddings(texts), 0
        try:
            response = await self._client.embeddings.create(model=model, input=texts, dimensions=1536)
        except Exception as error:
            raise classify_error(error) from error
        return [
            item.embedding for item in response.data
        ], response.usage.prompt_tokens if response.usage else 0


def classify_error(error: Exception) -> LLMError:
    if isinstance(error, RateLimitError):
        return LLMError(f"AI provider rate limit: {error}", recoverable=True, kind=RATE_LIMITED)
    if isinstance(error, APITimeoutError | APIConnectionError):
        return LLMError(f"AI provider temporarily unavailable: {error}", recoverable=True, kind=TRANSIENT)
    if isinstance(error, APIStatusError):
        message = f"AI provider error {error.status_code}: {error.message}"
        code = str(getattr(error, "code", "") or "")
        if error.status_code == 404 or code == "model_not_found":
            return LLMError(message, recoverable=False, kind=MODEL_UNAVAILABLE)
        if error.status_code in (401, 403):
            return LLMError(message, recoverable=False, kind=AUTH)
        return LLMError(
            message,
            recoverable=error.status_code >= 500,
            kind=TRANSIENT if error.status_code >= 500 else INVALID_REQUEST,
        )
    return LLMError(f"AI provider call failed: {error!r}", recoverable=True, kind=TRANSIENT)


def local_embeddings(texts: list[str]) -> list[list[float]]:
    # Deterministic hashed bag-of-words vectors: offline, free, good enough for keyword-ish recall
    vectors = []
    for text in texts:
        vector = [0.0] * 1536
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            if len(token) < 3:
                continue
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % 1536
            vector[index] += 1.0 if digest[4] % 2 else -1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        vectors.append([value / norm for value in vector])
    return vectors


def approximate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
