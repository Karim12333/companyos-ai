from enum import StrEnum

from companyos.models.enums import MemberRole


class Permission(StrEnum):
    VIEW = "view"
    CREATE_OBJECTIVE = "objective:create"
    CONTROL_OBJECTIVE = "objective:control"
    DECIDE_APPROVAL = "approval:decide"
    GIVE_FEEDBACK = "feedback:give"
    MANAGE_KNOWLEDGE = "knowledge:manage"
    MANAGE_PROJECTS = "project:manage"
    MANAGE_ORGANIZATION = "organization:manage"
    MANAGE_MEMBERS = "members:manage"
    MANAGE_INTEGRATIONS = "integrations:manage"
    MANAGE_SETTINGS = "settings:manage"


_MEMBER = {
    Permission.VIEW,
    Permission.CREATE_OBJECTIVE,
    Permission.CONTROL_OBJECTIVE,
    Permission.GIVE_FEEDBACK,
    Permission.MANAGE_KNOWLEDGE,
    Permission.MANAGE_PROJECTS,
}
_ADMIN = _MEMBER | {
    Permission.DECIDE_APPROVAL,
    Permission.MANAGE_ORGANIZATION,
    Permission.MANAGE_MEMBERS,
    Permission.MANAGE_INTEGRATIONS,
    Permission.MANAGE_SETTINGS,
}

ROLE_PERMISSIONS: dict[MemberRole, set[Permission]] = {
    MemberRole.VIEWER: {Permission.VIEW},
    MemberRole.MEMBER: _MEMBER,
    MemberRole.ADMIN: _ADMIN,
    MemberRole.OWNER: _ADMIN,
}


def has_permission(role: MemberRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())
