"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/api/errors";
import { getAuthMeQueryKey, useAuthChangePassword } from "@/lib/api/generated/auth/auth";
import { usePermissions } from "@/lib/permissions";

const schema = z
  .object({
    current_password: z.string().min(1, "Enter your current password"),
    new_password: z.string().min(12, "Use at least 12 characters"),
    confirm: z.string(),
  })
  .refine((v) => v.new_password === v.confirm, {
    path: ["confirm"],
    message: "Passwords don't match",
  });
type FormValues = z.infer<typeof schema>;

export function ChangePasswordForm() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { me } = usePermissions();
  const change = useAuthChangePassword();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  const onSubmit = async ({ current_password, new_password }: FormValues) => {
    await change.mutateAsync({ data: { current_password, new_password } });
    await queryClient.invalidateQueries({ queryKey: getAuthMeQueryKey() });
    router.replace("/operators");
  };

  return (
    <Card className="w-full max-w-sm">
      <CardHeader>
        <CardTitle>Change password</CardTitle>
        <CardDescription>
          {me?.must_change_password
            ? "You signed in with a temporary password. Choose a new one to continue."
            : "Other sessions will be signed out."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4" noValidate>
          {change.isError && (
            <Alert variant="destructive">
              <AlertDescription>{errorMessage(change.error)}</AlertDescription>
            </Alert>
          )}
          {(
            [
              ["current_password", "Current password", "current-password"],
              ["new_password", "New password", "new-password"],
              ["confirm", "Confirm new password", "new-password"],
            ] as const
          ).map(([name, label, autoComplete]) => (
            <div key={name} className="flex flex-col gap-2">
              <Label htmlFor={name}>{label}</Label>
              <Input id={name} type="password" autoComplete={autoComplete} {...register(name)} />
              {errors[name] && <p className="text-sm text-destructive">{errors[name]?.message}</p>}
            </div>
          ))}
          <Button type="submit" disabled={change.isPending}>
            {change.isPending ? "Saving…" : "Change password"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
