"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { RiskBadge } from "@/components/risk-inspections-list";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { errorMessage } from "@/lib/api/errors";
import type {
  RiskInspectionDetail,
  RiskInspectionPhoto,
  RiskInspectionZoneRead,
} from "@/lib/api/generated/model";
import { useRiskInspectionsGetRiskInspection } from "@/lib/api/generated/risk-inspections/risk-inspections";
import { useDocumentTitle } from "@/lib/use-document-title";

const fileUrl = (photo: RiskInspectionPhoto) => `/api/bff/v1/files/${photo.file_id}`;

const yesNo = (value: boolean | null | undefined) =>
  value === true ? "Yes" : value === false ? "No" : "";

/** The form's date and time are the store's wall-clock time, shown as written. */
function wallClock(value: string | null, part: "date" | "time"): string {
  if (!value) return "";
  const date = new Date(value);
  return part === "date"
    ? date.toLocaleDateString(undefined, { dateStyle: "medium" })
    : date.toLocaleTimeString(undefined, { timeStyle: "short" });
}

const list = (value: unknown) => (Array.isArray(value) ? (value as string[]) : []);

/** What the PDF's Area(s) column shows: the areas checked, or the zone's own options
 * (dumpster, basement, exterior perimeter, mall). */
function zoneAreas(zone: RiskInspectionZoneRead): string[] {
  const a = zone.attributes;
  return [
    ...zone.areas,
    ...list(a.dumpster),
    ...list(a.basement),
    ...list(a.exterior_perimeter),
    ...list(a.mall),
  ];
}

const inspected = (zone: RiskInspectionZoneRead) => zone.inspected === "yes";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd>{children || "—"}</dd>
    </div>
  );
}

function ServiceInformation({ report: r }: { report: RiskInspectionDetail }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Service information</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Inspector">{r.inspector_name}</Field>
          <Field label="Date">{wallClock(r.inspected_at, "date")}</Field>
          <Field label="Time">{wallClock(r.inspected_at, "time")}</Field>
          <Field label="RAMP recommendation">
            {r.ramp_recommendation != null && `RAMP ${r.ramp_recommendation}`}
          </Field>
          <Field label="Store">
            {r.location_id ? (
              <Link href={`/locations/${r.location_id}`} className="text-primary hover:underline">
                {r.location_name ?? r.store_label}
              </Link>
            ) : (
              r.store_label
            )}
          </Field>
          <Field label="Address">{r.address}</Field>
          <Field label="City">{r.city}</Field>
          <Field label="Work order">
            {r.service_order_id ? (
              <Link
                href={`/service-orders/${r.service_order_id}`}
                className="text-primary hover:underline"
              >
                {r.work_order_ref}
              </Link>
            ) : (
              r.work_order_ref
            )}
          </Field>
        </dl>
      </CardContent>
    </Card>
  );
}

const TH = "py-2 pr-3 text-left align-bottom font-medium";
const TD = "py-2 pr-3 align-top";

function ZoneSummary({ zones }: { zones: RiskInspectionZoneRead[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Zone summary</CardTitle>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="border-b border-border text-xs text-muted-foreground">
            <tr>
              <th scope="col" className={TH}>
                Zone
              </th>
              <th scope="col" className={TH}>
                Inspected
              </th>
              <th scope="col" className={TH}>
                Activity
              </th>
              <th scope="col" className={TH}>
                Overall risk
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {zones.map((z) => (
              <tr key={z.zone_key}>
                <th scope="row" className={`${TD} font-medium`}>
                  {z.name}
                </th>
                <td className={TD}>
                  {z.inspected === "n/a" ? "N/A" : inspected(z) ? "Yes" : z.inspected ? "No" : "—"}
                </td>
                <td className={TD}>
                  {inspected(z) &&
                    (z.has_activity ? (
                      <Badge variant="warning">With activity</Badge>
                    ) : (
                      <span className="text-muted-foreground">No activity</span>
                    ))}
                </td>
                <td className={TD}>{inspected(z) && <RiskBadge risk={z.overall_risk} />}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function StationDetails({ zones }: { zones: RiskInspectionZoneRead[] }) {
  const columns: { label: string; value: (z: RiskInspectionZoneRead) => React.ReactNode }[] = [
    {
      label: "Area(s)",
      value: (z) =>
        zoneAreas(z).length > 0 && (
          <ul className="flex flex-col gap-0.5">
            {zoneAreas(z).map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        ),
    },
    { label: "Areas checked", value: (z) => yesNo(z.all_areas_inspected) },
    { label: "Doors are", value: (z) => z.doors_are.join(", ") },
    { label: "Door sweeps in good condition", value: (z) => yesNo(z.door_sweeps_ok) },
    { label: "Doors properly aligned", value: (z) => yesNo(z.doors_aligned) },
    { label: "Rodent activity", value: (z) => yesNo(z.rodent_activity) },
    { label: "Pest activity", value: (z) => yesNo(z.pest_activity) },
    { label: "Pest type", value: (z) => z.pest_types.join(", ") },
    { label: "Trash room", value: (z) => list(z.attributes.trash_room).join(", ") },
    { label: "Ceiling", value: (z) => list(z.attributes.ceiling).join(", ") },
    { label: "Paneling", value: (z) => list(z.attributes.paneling).join(", ") },
    {
      label: "Dumbwaiter operational",
      value: (z) =>
        typeof z.attributes.dumbwaiter_operational === "boolean"
          ? yesNo(z.attributes.dumbwaiter_operational)
          : "",
    },
    { label: "Sanitation risk", value: (z) => <RiskBadge risk={z.sanitation_risk} /> },
    { label: "Structural risk", value: (z) => <RiskBadge risk={z.structural_risk} /> },
    { label: "Overall zone risk", value: (z) => <RiskBadge risk={z.overall_risk} /> },
  ];
  const shown = zones.filter(inspected);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Station details</CardTitle>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full min-w-[64rem] text-sm">
          <thead className="border-b border-border text-xs text-muted-foreground">
            <tr>
              <th scope="col" className={TH}>
                Zone
              </th>
              {columns.map((c) => (
                <th key={c.label} scope="col" className={TH}>
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {shown.map((z) => (
              <tr key={z.zone_key}>
                <th scope="row" className={`${TD} min-w-40 font-medium`}>
                  {z.name}
                </th>
                {columns.map((c) => (
                  <td key={c.label} className={TD}>
                    {c.value(z)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function Photos({ photos }: { photos: RiskInspectionPhoto[] }) {
  if (photos.length === 0) return null;
  return (
    <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {photos.map((p) => (
        <li key={p.file_id}>
          <a href={fileUrl(p)} target="_blank" rel="noopener noreferrer" className="block">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={fileUrl(p)}
              alt={p.file_name}
              loading="lazy"
              className="aspect-square w-full rounded-lg border border-border object-cover"
            />
          </a>
        </li>
      ))}
    </ul>
  );
}

const NOTE_SECTIONS = [
  { category: "pest", label: "Pest activity", notes: (z: RiskInspectionZoneRead) => z.pest_notes },
  {
    category: "sanitation",
    label: "Sanitation issues",
    notes: (z: RiskInspectionZoneRead) => z.sanitation_notes,
  },
  {
    category: "structural",
    label: "Structural integrity issues",
    notes: (z: RiskInspectionZoneRead) => z.structural_notes,
  },
  {
    category: "additional",
    label: "Additional notes",
    notes: (z: RiskInspectionZoneRead) => z.additional_notes,
  },
] as const;

function ZoneNotes({ zone }: { zone: RiskInspectionZoneRead }) {
  const sections = NOTE_SECTIONS.map((s) => ({
    ...s,
    text: s.notes(zone),
    photos: zone.photos.filter((p) => p.category === s.category),
  })).filter((s) => s.text || s.photos.length > 0);
  if (sections.length === 0) return null;
  return (
    <section className="flex flex-col gap-4 border-t border-border pt-4 first:border-t-0 first:pt-0">
      <h3 className="text-lg font-medium">{zone.name}</h3>
      {sections.map((s) => (
        <div key={s.category} className="flex flex-col gap-2">
          <h4 className="text-sm font-medium text-muted-foreground">{s.label}</h4>
          {s.text && <p className="whitespace-pre-line">{s.text}</p>}
          <Photos photos={s.photos} />
        </div>
      ))}
    </section>
  );
}

function MaterialUse({ report: r }: { report: RiskInspectionDetail }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Material use</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {r.materials.map((m) => (
            <Field key={m.material_key} label={m.name}>
              {m.quantity != null ? String(m.quantity) : yesNo(m.used)}
            </Field>
          ))}
        </dl>
        {r.material_notes && (
          <div>
            <h4 className="text-sm font-medium text-muted-foreground">Notes on material use</h4>
            <p className="whitespace-pre-line">{r.material_notes}</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/** A risk inspection laid out like GoCanvas's RiskGate PDF report. */
export function RiskInspectionReport() {
  const { inspectionId } = useParams<{ inspectionId: string }>();
  const query = useRiskInspectionsGetRiskInspection(inspectionId);
  const r = query.data?.data;
  useDocumentTitle(r ? `Risk inspection ${wallClock(r.inspected_at, "date")}` : undefined);

  if (query.isPending) return <p className="text-muted-foreground">Loading…</p>;
  if (query.isError || !r) {
    return (
      <Alert variant="destructive">
        <AlertDescription>
          {errorMessage(query.error, "Could not load the risk inspection.")}
        </AlertDescription>
      </Alert>
    );
  }
  const withNotes = r.zones.filter(inspected);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <Breadcrumbs trail={r.trail} />
        <h1 className="mt-2 text-3xl">RiskGate inspection</h1>
        <p className="flex flex-wrap items-center gap-2 text-muted-foreground">
          <span>
            {[r.location_name ?? r.store_label, wallClock(r.inspected_at, "date")]
              .filter(Boolean)
              .join(" · ")}
          </span>
          {r.submission_number && <span>· Submission {r.submission_number}</span>}
          {r.is_revision && <Badge variant="outline">Revised</Badge>}
        </p>
      </div>

      {r.photos_pending > 0 && (
        <Alert>
          <AlertDescription>
            {r.photos_pending} photo field{r.photos_pending === 1 ? "" : "s"} haven&apos;t been
            fetched from GoCanvas yet.
          </AlertDescription>
        </Alert>
      )}

      <ServiceInformation report={r} />
      <ZoneSummary zones={r.zones} />
      <StationDetails zones={r.zones} />

      <Card>
        <CardHeader>
          <CardTitle>Notes and images by technician</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-6">
          {withNotes.map((z) => (
            <ZoneNotes key={z.zone_key} zone={z} />
          ))}
        </CardContent>
      </Card>

      <MaterialUse report={r} />

      {r.manager_summary && (
        <Card>
          <CardHeader>
            <CardTitle>Service manager summary</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="whitespace-pre-line">{r.manager_summary}</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
