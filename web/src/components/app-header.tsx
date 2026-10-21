"use client";

import { useQueryClient } from "@tanstack/react-query";
import { LogOut } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { CSRF_HEADER, readCsrfToken } from "@/lib/csrf";
import { usePermissions } from "@/lib/permissions";

export function AppHeader() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { me, canAnywhere } = usePermissions();

  const logout = async () => {
    const res = await fetch("/api/auth/logout", {
      method: "POST",
      headers: { [CSRF_HEADER]: readCsrfToken() ?? "" },
    });
    if (!res.ok) console.error(`Logout failed with ${res.status}`);
    queryClient.clear();
    router.replace("/login");
    router.refresh();
  };

  return (
    <header className="border-b border-border bg-card">
      <div className="mx-auto flex h-14 w-full max-w-5xl items-center justify-between px-6">
        <nav className="flex items-center gap-6">
          <span className="font-semibold">Customer Portal</span>
          {canAnywhere("operators:read") && !me?.must_change_password && (
            <Link href="/operators" className="text-sm text-muted-foreground hover:text-foreground">
              Operators
            </Link>
          )}
        </nav>
        <div className="flex items-center gap-3">
          {me && <span className="text-sm text-muted-foreground">{me.email}</span>}
          <Button variant="ghost" size="sm" onClick={logout}>
            <LogOut aria-hidden />
            Sign out
          </Button>
        </div>
      </div>
    </header>
  );
}
