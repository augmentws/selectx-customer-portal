"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

/**
 * A tab kept in the URL (`?tab=…`, or another parameter for tabs nested in a page), so Back,
 * reload, and shared links return to it. Switching tabs pushes a history entry; the default tab
 * leaves the parameter out. An unknown value in the URL falls back to the default.
 */
export function useUrlTab<T extends string>(
  values: readonly T[],
  fallback: T,
  param = "tab",
): [T, (value: string) => void] {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const current = searchParams.get(param);
  const tab = values.includes(current as T) ? (current as T) : fallback;

  const setTab = useCallback(
    (value: string) => {
      const next = new URLSearchParams(searchParams.toString());
      if (value === fallback) next.delete(param);
      else next.set(param, value);
      const query = next.toString();
      router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [router, pathname, searchParams, param, fallback],
  );
  return [tab, setTab];
}
