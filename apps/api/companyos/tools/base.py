"""Core tool types shared by the registry and tool modules."""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from companyos.models.enums import RiskLevel
from companyos.providers.llm import LLMProvider


@dataclass
class ToolContext:
    organization_id: uuid.UUID
    agent_id: uuid.UUID
    agent_role_key: str
    objective_id: uuid.UUID | None
    task_id: uuid.UUID | None
    task_run_id: uuid.UUID | None
    llm: LLMProvider
    embedding_model: str
    max_messages_per_task: int = 6
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    content: str
    data: dict[str, Any] = field(default_factory=dict)
    untrusted: bool = False


class ToolExecutionError(Exception):
    """Expected tool failure; message is safe to show to the agent."""


Handler = Callable[[ToolContext, AsyncSession, Any], Awaitable[ToolResult]]


@dataclass(frozen=True)
class ToolDefinition:
    key: str
    description: str
    risk_level: RiskLevel
    args_model: type[BaseModel]
    handler: Handler
    # External tools change the outside world: executed once, tracked, never blindly repeated
    external: bool = False
    # True only when the provider deduplicates by our idempotency key, making re-sends safe
    provider_idempotent: bool = False
    # Default for Level 2 tools when the organization has no explicit policy row
    default_requires_approval: bool = True

    def json_schema(self) -> dict[str, Any]:
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        return schema
