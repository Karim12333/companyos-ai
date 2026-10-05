from companyos.templates.software_company import SOFTWARE_COMPANY
from companyos.templates.types import AgentSpec, DepartmentSpec, OrganizationTemplate

TEMPLATES: dict[str, OrganizationTemplate] = {SOFTWARE_COMPANY.key: SOFTWARE_COMPANY}

__all__ = ["TEMPLATES", "AgentSpec", "DepartmentSpec", "OrganizationTemplate"]
