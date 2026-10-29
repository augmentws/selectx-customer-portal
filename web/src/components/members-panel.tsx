"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient, type UseQueryOptions } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { errorMessage } from "@/lib/api/errors";
import {
  getMembersListCompanyMembersQueryOptions,
  getMembersListMembersQueryOptions,
  membersAddCompanyMember,
  membersAddMember,
  membersChangeCompanyRole,
  membersChangeRole,
  membersRemoveCompanyMember,
  membersRemoveMember,
} from "@/lib/api/generated/members/members";
import type {
  CompanyMemberRead,
  MemberCreate,
  MemberRead,
  RoleScope,
} from "@/lib/api/generated/model";
import { useRolesListRoles } from "@/lib/api/generated/roles/roles";
import { usePermissions } from "@/lib/permissions";

const addSchema = z.object({
  email: z.email("Enter a valid email"),
  role: z.string().min(1, "Choose a role"),
  temporary_password: z.union([z.literal(""), z.string().min(12, "Use at least 12 characters")]),
});
type AddValues = z.infer<typeof addSchema>;

function useRoleOptions(scope: RoleScope) {
  const roles = useRolesListRoles();
  return (roles.data?.data ?? []).filter((r) => r.scope === scope);
}

/** Whose members: a tenant's staff (the platform or an operator), or a company's own users. */
export type MembersTarget =
  | { kind: "tenant"; tenantId: string; roleScope: RoleScope }
  | { kind: "company"; companyId: string; operatorId: string };

type MemberList = { data: (MemberRead | CompanyMemberRead)[] };

/** The same list and changes for either kind of target, over their own endpoints. */
function useMembers(target: MembersTarget) {
  const queryClient = useQueryClient();
  const { can } = usePermissions();
  const tenant = target.kind === "tenant";
  const id = tenant ? target.tenantId : target.companyId;
  const listOptions = (
    tenant ? getMembersListMembersQueryOptions(id) : getMembersListCompanyMembersQueryOptions(id)
  ) as UseQueryOptions<MemberList>;
  const list = useQuery(listOptions);
  const onSuccess = () => queryClient.invalidateQueries({ queryKey: listOptions.queryKey });
  const add = useMutation({
    mutationFn: async (data: MemberCreate) =>
      (tenant ? await membersAddMember(id, data) : await membersAddCompanyMember(id, data)).data,
    onSuccess,
  });
  const changeRole = useMutation({
    mutationFn: async ({ userId, role }: { userId: string; role: string }) => {
      await (tenant
        ? membersChangeRole(id, userId, { role })
        : membersChangeCompanyRole(id, userId, { role }));
    },
    onSuccess,
  });
  const remove = useMutation({
    mutationFn: async (userId: string) => {
      await (tenant ? membersRemoveMember(id, userId) : membersRemoveCompanyMember(id, userId));
    },
    onSuccess,
  });
  return {
    roleScope: tenant ? target.roleScope : ("company" as const),
    // Company members are managed by whoever manages the operator's members.
    canWrite: can("members:write", tenant ? id : target.operatorId),
    list,
    add,
    changeRole,
    remove,
  };
}

type Members = ReturnType<typeof useMembers>;

function AddMemberForm({ add, roleScope }: { add: Members["add"]; roleScope: RoleScope }) {
  const roles = useRoleOptions(roleScope);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<AddValues>({
    resolver: zodResolver(addSchema),
    defaultValues: { email: "", role: "", temporary_password: "" },
  });

  const onSubmit = async ({ temporary_password, ...rest }: AddValues) => {
    await add.mutateAsync({ ...rest, temporary_password: temporary_password || null });
    reset();
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Add member</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <form
          onSubmit={handleSubmit(onSubmit)}
          className="grid gap-4 sm:grid-cols-[2fr_1fr_2fr_auto] sm:items-end"
          noValidate
        >
          <div className="flex flex-col gap-2">
            <Label htmlFor="member-email">Email</Label>
            <Input id="member-email" type="email" autoComplete="off" {...register("email")} />
            {errors.email && <p className="text-sm text-destructive">{errors.email.message}</p>}
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="member-role">Role</Label>
            <NativeSelect id="member-role" className="w-full" {...register("role")}>
              <NativeSelectOption value="">Choose…</NativeSelectOption>
              {roles.map((r) => (
                <NativeSelectOption key={r.name} value={r.name}>
                  {r.name}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            {errors.role && <p className="text-sm text-destructive">{errors.role.message}</p>}
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="member-password">Temporary password</Label>
            <Input
              id="member-password"
              type="password"
              autoComplete="new-password"
              {...register("temporary_password")}
            />
            {errors.temporary_password && (
              <p className="text-sm text-destructive">{errors.temporary_password.message}</p>
            )}
          </div>
          <Button type="submit" disabled={add.isPending}>
            Add
          </Button>
        </form>
        <p className="text-sm text-muted-foreground">
          Needed only for new users. They must change it when they first sign in.
        </p>
        {add.isError && (
          <Alert variant="destructive">
            <AlertDescription>{errorMessage(add.error)}</AlertDescription>
          </Alert>
        )}
        {add.isSuccess && (
          <Alert>
            <AlertDescription>
              {add.data.user_created
                ? `Created ${add.data.email}. Share the temporary password with them securely.`
                : `Added existing user ${add.data.email}.`}
            </AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
}

export function MembersPanel({ target }: { target: MembersTarget }) {
  const { me } = usePermissions();
  const { roleScope, canWrite, list: members, add, changeRole, remove } = useMembers(target);
  const roles = useRoleOptions(roleScope);
  const mutationError = changeRole.error ?? remove.error;

  return (
    <div className="flex flex-col gap-6">
      {canWrite && <AddMemberForm add={add} roleScope={roleScope} />}
      {mutationError && (
        <Alert variant="destructive">
          <AlertDescription>{errorMessage(mutationError)}</AlertDescription>
        </Alert>
      )}
      {members.isPending && <p className="text-muted-foreground">Loading…</p>}
      {members.isError && (
        <Alert variant="destructive">
          <AlertDescription>
            {errorMessage(members.error, "Could not load members.")}
          </AlertDescription>
        </Alert>
      )}
      {members.data && (
        <ul className="divide-y divide-border rounded-lg border border-border bg-card">
          {members.data.data.length === 0 && (
            <li className="p-4 text-muted-foreground">No members yet.</li>
          )}
          {members.data.data.map((m) => (
            <li key={m.user_id} className="flex flex-wrap items-center justify-between gap-3 p-4">
              <span className="flex items-center gap-2">
                {m.email}
                {m.user_id === me?.id && <Badge variant="outline">You</Badge>}
                {m.must_change_password && <Badge variant="warning">Temporary password</Badge>}
              </span>
              {canWrite ? (
                <span className="flex items-center gap-2">
                  <NativeSelect
                    size="sm"
                    aria-label={`Role for ${m.email}`}
                    value={m.role}
                    disabled={changeRole.isPending}
                    onChange={(e) => changeRole.mutate({ userId: m.user_id, role: e.target.value })}
                  >
                    {roles.map((r) => (
                      <NativeSelectOption key={r.name} value={r.name}>
                        {r.name}
                      </NativeSelectOption>
                    ))}
                  </NativeSelect>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={remove.isPending}
                    onClick={() => remove.mutate(m.user_id)}
                  >
                    Remove
                  </Button>
                </span>
              ) : (
                <span className="text-sm text-muted-foreground">{m.role}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
