"use client";

// Mirrors app/security/access.py so the UI shows only what the API will allow. FastAPI still
// enforces every permission; this only decides what to render.
import type { ReactNode } from "react";

import { useAuthMe } from "@/lib/api/generated/auth/auth";
import type { MeRead } from "@/lib/api/generated/model";

export type PermissionCode =
  | "operators:read"
  | "operators:write"
  | "companies:read"
  | "companies:write"
  | "bill_tos:read"
  | "bill_tos:write"
  | "members:read"
  | "members:write"
  | "roles:read"
  | "pestpac_connection:read"
  | "pestpac_connection:write"
  | "reports:read"
  | "reports:write"
  | "report_templates:write"
  | "dashboards:read"
  | "webhooks:read"
  | "billing:read";

export function permissionsOn(me: MeRead | undefined, tenantId: string | undefined): Set<string> {
  const perms = new Set<string>();
  if (!me) return perms;
  for (const m of me.memberships) {
    // A platform grant applies to every tenant; an operator grant only to that operator.
    if (m.tenant_kind === "platform" || m.tenant_id === tenantId) {
      m.permissions.forEach((p) => perms.add(p));
    }
  }
  return perms;
}

/** Permissions on one company: its operator's, plus the caller's own grant on that company
 * (a customer's user). Only the routes FastAPI opens to company users honour the grant. */
export function permissionsOnCompany(
  me: MeRead | undefined,
  companyId: string | undefined,
  operatorId: string | undefined,
): Set<string> {
  const perms = permissionsOn(me, operatorId);
  me?.company_memberships
    .find((c) => c.company_id === companyId)
    ?.permissions.forEach((p) => perms.add(p));
  return perms;
}

export function hasAnywhere(me: MeRead | undefined, perm: PermissionCode): boolean {
  return !!me?.memberships.some((m) => m.permissions.includes(perm));
}

export function usePermissions() {
  const { data, isPending } = useAuthMe();
  const me = data?.data;
  return {
    me,
    isPending,
    can: (perm: PermissionCode, tenantId?: string) => permissionsOn(me, tenantId).has(perm),
    canOnCompany: (perm: PermissionCode, companyId?: string, operatorId?: string) =>
      permissionsOnCompany(me, companyId, operatorId).has(perm),
    canAnywhere: (perm: PermissionCode) => hasAnywhere(me, perm),
    platformTenantId: me?.memberships.find((m) => m.tenant_kind === "platform")?.tenant_id,
  };
}

export function Can({
  perm,
  tenantId,
  children,
  fallback = null,
}: {
  perm: PermissionCode;
  tenantId?: string;
  children: ReactNode;
  fallback?: ReactNode;
}) {
  const { can } = usePermissions();
  return <>{can(perm, tenantId) ? children : fallback}</>;
}
