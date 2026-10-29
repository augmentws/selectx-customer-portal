"use client";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { errorMessage } from "@/lib/api/errors";
import { useContactsListLocationContacts } from "@/lib/api/generated/contacts/contacts";
import type { ContactRole } from "@/lib/api/generated/model";

const ROLE_LABELS: Record<ContactRole, string> = {
  store: "Restaurant",
  executive_team_director: "Executive Team Director",
  team_director: "Team Director",
  restaurant_leader: "Restaurant Leader",
};

/** The location's contacts from the customer (the Restaurant Leader Report), in the API's
 * order: the restaurant's own phone and email, then its leaders from the top down. */
export function LocationContacts({ locationId }: { locationId: string }) {
  const contacts = useContactsListLocationContacts(locationId);

  if (contacts.isPending) return <p className="text-muted-foreground">Loading…</p>;
  if (contacts.isError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>
          {errorMessage(contacts.error, "Could not load contacts.")}
        </AlertDescription>
      </Alert>
    );
  }
  const list = contacts.data.data;
  if (list.length === 0) {
    return (
      <p className="border border-border bg-card p-4 text-muted-foreground">
        No contacts yet. They come from the customer&apos;s Restaurant Leader Report.
      </p>
    );
  }
  return (
    <ul className="divide-y divide-border border border-border bg-card">
      {list.map((c) => (
        <li key={c.id} className="grid gap-x-6 gap-y-1 p-4 text-sm sm:grid-cols-3">
          <div>
            <div className="font-medium">{c.name ?? "—"}</div>
            <div className="text-muted-foreground">{ROLE_LABELS[c.role]}</div>
          </div>
          <span>
            {c.email ? (
              <a href={`mailto:${c.email}`} className="text-primary hover:underline">
                {c.email}
              </a>
            ) : (
              "—"
            )}
          </span>
          <span>
            {c.phone ? (
              <a href={`tel:${c.phone}`} className="text-primary hover:underline">
                {c.phone}
              </a>
            ) : (
              "—"
            )}
          </span>
        </li>
      ))}
    </ul>
  );
}
