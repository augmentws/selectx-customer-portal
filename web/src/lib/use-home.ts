"use client";

import { useOperatorsListOperators } from "@/lib/api/generated/operators/operators";
import { usePermissions } from "@/lib/permissions";

export const OPERATORS_HREF = "/operators";

/** Where "home" is. Someone who sees a single operator and can't add operators has no use for
 * the operators list, so their home is that operator. Everyone else starts at the list. */
export function useHomeHref(): string {
  const { canAnywhere, platformTenantId, can, me } = usePermissions();
  const canList = canAnywhere("operators:read") && !me?.must_change_password;
  const operators = useOperatorsListOperators({ query: { enabled: canList } });
  const canAdd = platformTenantId !== undefined && can("operators:write", platformTenantId);
  const list = operators.data?.data;
  return !canAdd && list?.length === 1 ? `${OPERATORS_HREF}/${list[0].id}` : OPERATORS_HREF;
}
