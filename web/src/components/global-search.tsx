"use client";

import { keepPreviousData } from "@tanstack/react-query";
import {
  Building2,
  ClipboardList,
  Landmark,
  MapPin,
  Receipt,
  Search,
  Store,
  type LucideIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@/components/ui/combobox";
import { useSearchSearch } from "@/lib/api/generated/search/search";
import type { SearchHit } from "@/lib/api/generated/model";

const MIN_LENGTH = 2;
const DEBOUNCE_MS = 250;

const KINDS: Record<SearchHit["kind"], { label: string; icon: LucideIcon }> = {
  operator: { label: "Operator", icon: Landmark },
  company: { label: "Company", icon: Building2 },
  bill_to: { label: "Bill-to", icon: Store },
  location: { label: "Location", icon: MapPin },
  service_order: { label: "Service order", icon: ClipboardList },
  invoice: { label: "Invoice", icon: Receipt },
};

function hrefFor(hit: SearchHit): string {
  switch (hit.kind) {
    case "operator":
      return `/operators/${hit.id}`;
    case "company":
      return `/companies/${hit.id}`;
    case "bill_to":
      return `/bill-tos/${hit.id}`;
    case "location":
      return `/locations/${hit.id}`;
    // Orders and invoices are shown on their location's page.
    case "service_order":
    case "invoice":
      return `/locations/${hit.location_id}`;
  }
}

function useDebounced(value: string, ms: number): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

/** Header search for companies, bill-tos, locations (name, store number, address, ids), and
 * service order and invoice numbers. Press "/" anywhere to focus it. */
export function GlobalSearch() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [input, setInput] = useState("");
  const q = useDebounced(input.trim(), DEBOUNCE_MS);
  const ready = q.length >= MIN_LENGTH;
  const search = useSearchSearch(
    { q },
    { query: { enabled: ready, placeholderData: keepPreviousData } },
  );
  const hits = ready ? (search.data?.data.items ?? []) : [];

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const typing =
        target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
      if (e.key === "/" && !typing && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  let empty = "Type at least two characters.";
  if (ready) {
    if (search.isError) empty = "Search failed. Try again.";
    else if (search.isFetching && hits.length === 0) empty = "Searching…";
    else empty = `Nothing matches “${q}”.`;
  }

  return (
    <Combobox<SearchHit>
      items={hits}
      // The server already filtered and ranked the hits.
      filter={null}
      inputValue={input}
      onInputValueChange={setInput}
      value={null}
      onValueChange={(hit) => {
        if (!hit) return;
        setInput("");
        inputRef.current?.blur();
        router.push(hrefFor(hit));
      }}
      itemToStringLabel={(hit) => hit.title}
      isItemEqualToValue={(a, b) => a.kind === b.kind && a.id === b.id}
      autoHighlight
    >
      <ComboboxInput
        ref={inputRef}
        placeholder="Search stores, orders…"
        aria-label="Search companies, locations, and orders"
        showTrigger={false}
        className="w-full"
      >
        <Search
          aria-hidden
          className="pointer-events-none order-first ml-2 size-4 shrink-0 text-muted-foreground"
        />
      </ComboboxInput>
      <ComboboxContent className="w-[min(28rem,calc(100vw-2rem))]">
        <ComboboxEmpty>{empty}</ComboboxEmpty>
        <ComboboxList>
          {(hit: SearchHit) => {
            const { label, icon: Icon } = KINDS[hit.kind];
            return (
              <ComboboxItem key={`${hit.kind}:${hit.id}`} value={hit} className="items-start">
                <Icon aria-hidden className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                <span className="flex min-w-0 flex-col">
                  <span className="truncate">{hit.title}</span>
                  <span className="truncate text-xs text-muted-foreground">
                    {label}
                    {hit.detail && ` · ${hit.detail}`}
                  </span>
                </span>
              </ComboboxItem>
            );
          }}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  );
}
