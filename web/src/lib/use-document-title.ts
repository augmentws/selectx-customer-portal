"use client";

import { useEffect } from "react";

const SUFFIX = "Select Exterminating";

/** Names the browser tab after the page, most specific part first. Parts still loading are
 * skipped; the default title comes back when the page unmounts. */
export function useDocumentTitle(...parts: (string | null | undefined)[]) {
  const title = [...parts.filter(Boolean), SUFFIX].join(" · ");
  useEffect(() => {
    const previous = document.title;
    document.title = title;
    return () => {
      document.title = previous;
    };
  }, [title]);
}
