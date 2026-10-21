"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuthMe } from "@/lib/api/generated/auth/auth";

const CHANGE_PASSWORD = "/change-password";

/** Sends users with a temporary password to the change-password page. The API refuses their
 * other requests anyway; this keeps the UI from showing a wall of errors. */
export function SessionGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { data, isPending, isError } = useAuthMe();
  const mustChange = data?.data.must_change_password ?? false;

  useEffect(() => {
    if (mustChange && pathname !== CHANGE_PASSWORD) router.replace(CHANGE_PASSWORD);
  }, [mustChange, pathname, router]);

  if (isPending) return <p className="text-muted-foreground">Loading…</p>;
  if (isError) return <p className="text-destructive">Could not load your session.</p>;
  if (mustChange && pathname !== CHANGE_PASSWORD) return null;
  return <>{children}</>;
}
