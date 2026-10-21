"""Permission codes and system roles.

This module is the source of truth. `app.services.rbac.sync_rbac` reconciles the database with
it, and a test asserts the latest migration already matches, so the two cannot drift silently.
Routes declare the permission they need; they never check role names.
"""

import enum


class Perm(enum.StrEnum):
    operators_read = "operators:read"
    operators_write = "operators:write"
    companies_read = "companies:read"
    companies_write = "companies:write"
    bill_tos_read = "bill_tos:read"
    bill_tos_write = "bill_tos:write"
    members_read = "members:read"
    members_write = "members:write"
    roles_read = "roles:read"
    pestpac_connection_read = "pestpac_connection:read"
    pestpac_connection_write = "pestpac_connection:write"


PERMISSION_DESCRIPTIONS: dict[Perm, str] = {
    Perm.operators_read: "View operators",
    Perm.operators_write: "Create and edit operators",
    Perm.companies_read: "View companies",
    Perm.companies_write: "Create and edit companies",
    Perm.bill_tos_read: "View bill-tos",
    Perm.bill_tos_write: "Onboard and edit bill-tos",
    Perm.members_read: "View members",
    Perm.members_write: "Add, change, and remove members",
    Perm.roles_read: "View roles and permissions",
    Perm.pestpac_connection_read: "View PestPac API connection status",
    Perm.pestpac_connection_write: "Set up and test PestPac API credentials",
}


class RoleScope(enum.StrEnum):
    """Which kind of tenant a role may be assigned on."""

    platform = "platform"
    operator = "operator"


class SystemRole(enum.StrEnum):
    platform_admin = "platform_admin"
    operator_admin = "operator_admin"
    operator_staff = "operator_staff"


SYSTEM_ROLES: dict[SystemRole, tuple[RoleScope, str, frozenset[Perm]]] = {
    SystemRole.platform_admin: (
        RoleScope.platform,
        "Full access to every operator, company, and bill-to",
        frozenset(Perm),
    ),
    SystemRole.operator_admin: (
        RoleScope.operator,
        "Manages one operator's companies, bill-tos, and members",
        frozenset(
            {
                Perm.operators_read,
                Perm.companies_read,
                Perm.companies_write,
                Perm.bill_tos_read,
                Perm.bill_tos_write,
                Perm.members_read,
                Perm.members_write,
                Perm.roles_read,
                Perm.pestpac_connection_read,
                Perm.pestpac_connection_write,
            }
        ),
    ),
    SystemRole.operator_staff: (
        RoleScope.operator,
        "Read-only access to one operator's companies and bill-tos",
        frozenset({Perm.operators_read, Perm.companies_read, Perm.bill_tos_read}),
    ),
}
