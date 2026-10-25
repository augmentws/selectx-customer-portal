"use client";

import { useQueryClient } from "@tanstack/react-query";
import { LogOut } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { BrandLogo } from "@/components/brand";
import { Button } from "@/components/ui/button";
import { CSRF_HEADER, readCsrfToken } from "@/lib/csrf";
import { usePermissions } from "@/lib/permissions";
import { OPERATORS_HREF, useHomeHref } from "@/lib/use-home";

export function AppHeader() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { me, canAnywhere } = usePermissions();
  const home = useHomeHref();

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
    <header className="border-b-4 border-highlight bg-background">
      <div className="mx-auto flex h-16 w-full max-w-5xl items-center justify-between px-6">
        <nav className="flex items-center gap-6">
          <BrandLogo href={home} />
          {home === OPERATORS_HREF &&
            canAnywhere("operators:read") &&
            !me?.must_change_password && (
              <Link
                href="/operators"
                className="font-heading text-sm font-medium tracking-wide text-foreground uppercase hover:text-primary"
              >
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
