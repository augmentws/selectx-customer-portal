"use client";

import { formatPestPacDate } from "@/components/service-order-list";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { errorMessage } from "@/lib/api/errors";
import { useLocationsListAreas } from "@/lib/api/generated/locations/locations";
import { cn } from "@/lib/utils";

/** The location's areas as PestPac defines them, in the API's tree order (each parent, then its
 * children), indented by depth, with each area's open conditions. */
export function LocationAreas({ locationId }: { locationId: string }) {
  const areas = useLocationsListAreas(locationId);

  if (areas.isPending) return <p className="text-muted-foreground">Loading…</p>;
  if (areas.isError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{errorMessage(areas.error, "Could not load areas.")}</AlertDescription>
      </Alert>
    );
  }
  const list = areas.data.data;
  if (list.length === 0) {
    return (
      <p className="border border-border bg-card p-4 text-muted-foreground">
        No areas yet. They&apos;re set up in PestPac and come in with &ldquo;Documents and
        conditions&rdquo;.
      </p>
    );
  }
  return (
    <ul className="divide-y divide-border border border-border bg-card">
      {list.map((a) => (
        <li
          key={a.id}
          className="flex flex-wrap items-center gap-x-3 gap-y-1 py-3 pr-4 text-sm"
          // Indent by depth: 1rem for top-level areas, then 1.5rem per level.
          style={{ paddingLeft: `${1 + (a.depth - 1) * 1.5}rem` }}
        >
          <span
            className={cn(a.depth === 1 && "font-medium", !a.active && "text-muted-foreground")}
          >
            {a.name}
          </span>
          {a.area_type && <Badge variant="outline">{a.area_type.toLowerCase()}</Badge>}
          {!a.active && <Badge variant="outline">Inactive</Badge>}
          {a.open_conditions > 0 && (
            <Badge variant="warning">
              {a.open_conditions} open condition{a.open_conditions === 1 ? "" : "s"}
            </Badge>
          )}
          <span className="ml-auto text-muted-foreground">
            {a.last_inspection_date
              ? `Inspected ${formatPestPacDate(a.last_inspection_date)}`
              : "Not inspected"}
          </span>
        </li>
      ))}
    </ul>
  );
}
