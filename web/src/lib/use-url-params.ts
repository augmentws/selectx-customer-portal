"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

/** Filters kept in the URL, so Back and shared links return to the same view. Changes replace
 * the history entry (typing shouldn't add one per keystroke); empty values are left out. */
export function useUrlParams<K extends string>(
  keys: readonly K[],
): [Record<K, string>, (changes: Partial<Record<K, string>>) => void] {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const values = Object.fromEntries(keys.map((k) => [k, searchParams.get(k) ?? ""])) as Record<
    K,
    string
  >;
  const set = useCallback(
    (changes: Partial<Record<K, string>>) => {
      const next = new URLSearchParams(searchParams.toString());
      for (const [k, v] of Object.entries(changes) as [K, string | undefined][]) {
        if (v) next.set(k, v);
        else next.delete(k);
      }
      const query = next.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [router, pathname, searchParams],
  );
  return [values, set];
}
