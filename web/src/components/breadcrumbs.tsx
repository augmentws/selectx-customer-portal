"use client";

import Link from "next/link";

import type { Crumb } from "@/lib/api/generated/model";
import { OPERATORS_HREF, useHomeHref } from "@/lib/use-home";

const HREF: Record<Crumb["kind"], string> = {
  operator: "/operators",
  company: "/companies",
  bill_to: "/bill-tos",
  location: "/locations",
};

/** Where a record sits: the operators list (for those who use it), then the record's parents
 * from the API's `trail`. The page's own heading names the record itself. */
export function Breadcrumbs({ trail }: { trail: Crumb[] }) {
  const showOperators = useHomeHref() === OPERATORS_HREF;
  const links = [
    ...(showOperators ? [{ key: "operators", href: OPERATORS_HREF, name: "Operators" }] : []),
    ...trail.map((c) => ({ key: c.id, href: `${HREF[c.kind]}/${c.id}`, name: c.name })),
  ];
  if (links.length === 0) return null;
  return (
    <nav aria-label="Breadcrumb">
      <ol className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted-foreground">
        {links.map((l, i) => (
          <li key={l.key} className="flex items-center gap-2">
            {i > 0 && <span aria-hidden>/</span>}
            <Link href={l.href} className="hover:text-foreground hover:underline">
              {l.name}
            </Link>
          </li>
        ))}
      </ol>
    </nav>
  );
}
