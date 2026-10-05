from dataclasses import dataclass, field


@dataclass(frozen=True)
class DepartmentSpec:
    slug: str
    name: str
    description: str
    sort_order: int


@dataclass(frozen=True)
class AgentSpec:
    role_key: str
    name: str
    title: str
    department: str
    manager: str | None
    description: str
    instructions: str
    goals: list[str]
    responsibilities: list[str]
    tools: list[str]
    delegates_to: list[str] = field(default_factory=list)
    is_coordinator: bool = False
    is_department_manager: bool = False
    use_premium_model: bool = False


@dataclass(frozen=True)
class OrganizationTemplate:
    key: str
    name: str
    description: str
    departments: list[DepartmentSpec]
    agents: list[AgentSpec]
