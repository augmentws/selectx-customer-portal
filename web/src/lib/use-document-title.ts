"use client";

import { useEffect } from "react";

const SUFFIX = "Select Exterminating";

/** Names the browser tab after the page, most specific part first. Parts still loading are
 * skipped; the default title comes back when the page unmounts.
 *
 * Next.js rewrites the title from the layout's metadata after every navigation (switching a
 * URL tab too), later than our effects run, so the title is watched and put back. */
export function useDocumentTitle(...parts: (string | null | undefined)[]) {
  // Whitespace collapsed as the browser does: document.title reads back "A  B" as "A B", so an
  // uncollapsed title would never match, and setting it again would retrigger the observer
  // forever (a frozen page, e.g. for a store named "MAGGIANOS  KING OF PRUSSIA").
  const title = [...parts.filter(Boolean), SUFFIX].join(" · ").replace(/\s+/g, " ").trim();
  useEffect(() => {
    const previous = document.title;
    const apply = () => {
      if (document.title !== title) document.title = title;
    };
    apply();
    // The <title> element may be replaced as well as edited, so watch the whole head.
    const observer = new MutationObserver(apply);
    observer.observe(document.head, { subtree: true, childList: true, characterData: true });
    return () => {
      observer.disconnect();
      document.title = previous;
    };
  }, [title]);
}
