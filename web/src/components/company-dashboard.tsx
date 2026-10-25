"use client";

import { ArrowDown, ArrowUp } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { ReportTemplatesSection } from "@/components/report-templates";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  type ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/page-tabs";
import { useDocumentTitle } from "@/lib/use-document-title";
import { errorMessage } from "@/lib/api/errors";
import {
  useCompaniesGetCompany,
  useCompaniesListBillTos,
} from "@/lib/api/generated/companies/companies";
import { useDashboardGetCompanyDashboard } from "@/lib/api/generated/dashboard/dashboard";
import type {
  CompanyDashboard,
  MonthCount,
  ServiceCodeCount,
  StoreRow,
} from "@/lib/api/generated/model";
import { usePermissions } from "@/lib/permissions";
import { useUrlTab } from "@/lib/use-url-tab";

const DAY_MS = 864e5;
const integer = new Intl.NumberFormat();
const compact = new Intl.NumberFormat(undefined, { notation: "compact" });

/** PestPac dates are local wall-clock times without an offset; show them as-is. */
function formatDate(value: string | null | undefined) {
  return value ? new Date(value).toLocaleDateString(undefined, { dateStyle: "medium" }) : "—";
}

function formatMonth(month: string, style: "short" | "long" = "short") {
  const [year, m] = month.split("-").map(Number);
  return new Date(year, m - 1, 1).toLocaleDateString(undefined, {
    month: style,
    year: style === "short" ? "2-digit" : "numeric",
  });
}

function daysSince(asOf: string, value: string | null) {
  if (!value) return null;
  return Math.max(0, Math.floor((Date.parse(asOf) - new Date(value).getTime()) / DAY_MS));
}

function StatTile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-border bg-card p-4">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className="text-2xl font-semibold">{value}</span>
      {note && <span className="text-xs text-muted-foreground">{note}</span>}
    </div>
  );
}

const servicesConfig = {
  services: { label: "Services", color: "var(--chart-1)" },
} satisfies ChartConfig;

/** A chart's data as a table, for screen readers and exact values. */
function DataTable({ caption, rows }: { caption: string; rows: [string, number][] }) {
  return (
    <details className="text-sm">
      <summary className="cursor-pointer text-primary hover:underline">Show table</summary>
      <table className="mt-2 w-full max-w-sm">
        <caption className="sr-only">{caption}</caption>
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label} className="border-b border-border last:border-0">
              <th scope="row" className="py-1 text-left font-normal">
                {label}
              </th>
              <td className="py-1 text-right tabular-nums">{integer.format(value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

function ServicesByMonth({ data }: { data: MonthCount[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Services by month</CardTitle>
        <CardDescription>Worked orders, by work date</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <ChartContainer config={servicesConfig} className="aspect-auto h-64 w-full">
          <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--border)" />
            <XAxis
              dataKey="month"
              tickLine={false}
              axisLine={false}
              tickMargin={8}
              tickFormatter={(m: string) => formatMonth(m)}
            />
            <YAxis
              allowDecimals={false}
              tickLine={false}
              axisLine={false}
              width={36}
              tickFormatter={(v: number) => compact.format(v)}
            />
            <ChartTooltip
              cursor={{ fill: "var(--muted)" }}
              content={
                <ChartTooltipContent labelFormatter={(m) => formatMonth(String(m), "long")} />
              }
            />
            <Bar
              dataKey="services"
              fill="var(--color-services)"
              radius={[4, 4, 0, 0]}
              maxBarSize={24}
            />
          </BarChart>
        </ChartContainer>
        <DataTable
          caption="Services by month"
          rows={data.map((d) => [formatMonth(d.month, "long"), d.services])}
        />
      </CardContent>
    </Card>
  );
}

const MAX_CODES = 10;

function ServicesByCode({ data }: { data: ServiceCodeCount[] }) {
  const rows = useMemo(() => {
    const named = data.map((d) => ({ code: d.service_code ?? "No code", services: d.services }));
    if (named.length <= MAX_CODES) return named;
    const other = named.slice(MAX_CODES - 1).reduce((t, d) => t + d.services, 0);
    return [...named.slice(0, MAX_CODES - 1), { code: "Other codes", services: other }];
  }, [data]);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Services by service code</CardTitle>
        <CardDescription>Worked orders, by PestPac service code</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <ChartContainer
          config={servicesConfig}
          className="aspect-auto w-full"
          style={{ height: Math.max(rows.length * 36, 72) }}
        >
          <BarChart
            data={rows}
            layout="vertical"
            margin={{ top: 0, right: 16, left: 0, bottom: 0 }}
          >
            <CartesianGrid horizontal={false} stroke="var(--border)" />
            <XAxis
              type="number"
              allowDecimals={false}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v: number) => compact.format(v)}
            />
            <YAxis type="category" dataKey="code" tickLine={false} axisLine={false} width={130} />
            <ChartTooltip cursor={{ fill: "var(--muted)" }} content={<ChartTooltipContent />} />
            <Bar
              dataKey="services"
              fill="var(--color-services)"
              radius={[0, 4, 4, 0]}
              maxBarSize={24}
            />
          </BarChart>
        </ChartContainer>
        <DataTable
          caption="Services by service code"
          rows={rows.map((r) => [r.code, r.services])}
        />
      </CardContent>
    </Card>
  );
}

function Overview({ d }: { d: CompanyDashboard }) {
  const h = d.headline;
  return (
    <div className="flex flex-col gap-6">
      {h.services === 0 && (
        <Alert>
          <AlertDescription>
            No worked service orders yet. Use “Sync service orders” on a bill-to or location page
            (with the background worker running) to pull them from PestPac.
          </AlertDescription>
        </Alert>
      )}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatTile
          label="Locations"
          value={integer.format(h.locations)}
          note={`${integer.format(h.locations_serviced)} serviced`}
        />
        <StatTile
          label="Services"
          value={integer.format(h.services)}
          note={
            h.first_service
              ? `${formatDate(h.first_service)} to ${formatDate(h.last_service)}`
              : undefined
          }
        />
        <StatTile label="Open orders" value={integer.format(h.open_orders)} />
        <StatTile label="Technicians" value={integer.format(h.technicians)} />
        <StatTile label="Awaiting billing" value={integer.format(h.awaiting_billing)} />
        <StatTile label="Billed" value={integer.format(h.billed)} />
        <StatTile label="Last service" value={formatDate(h.last_service)} />
      </div>
      {d.services_by_month.length > 0 && <ServicesByMonth data={d.services_by_month} />}
      <div className="grid gap-6 lg:grid-cols-2">
        {d.services_by_code.length > 0 && <ServicesByCode data={d.services_by_code} />}
        {d.top_technicians.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Top technicians</CardTitle>
              <CardDescription>By worked orders</CardDescription>
            </CardHeader>
            <CardContent>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-muted-foreground">
                    <th className="py-2 font-medium">Technician</th>
                    <th className="py-2 text-right font-medium">Services</th>
                  </tr>
                </thead>
                <tbody>
                  {d.top_technicians.map((t) => (
                    <tr
                      key={`${t.technician_id}-${t.name}`}
                      className="border-b border-border last:border-0"
                    >
                      <td className="py-2">{t.name ?? "Unknown"}</td>
                      <td className="py-2 text-right tabular-nums">{integer.format(t.services)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}

type SortKey = "store" | "name" | "services" | "open_orders" | "last_service";

const COLUMNS: { key: SortKey; label: string; numeric?: boolean }[] = [
  { key: "store", label: "Store #" },
  { key: "name", label: "Location" },
  { key: "services", label: "Services", numeric: true },
  { key: "open_orders", label: "Open orders", numeric: true },
  { key: "last_service", label: "Last service" },
];

function sortValue(row: StoreRow, key: SortKey): string | number {
  switch (key) {
    case "store":
      return row.store_number ? Number(row.store_number) : Number.MAX_SAFE_INTEGER;
    case "name":
      return row.name ?? "";
    case "last_service":
      return row.last_service ?? "";
    default:
      return row[key];
  }
}

function Stores({ d }: { d: CompanyDashboard }) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({
    key: "services",
    desc: true,
  });
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q
      ? d.stores.filter((s) =>
          [s.name, s.store_number, s.city, s.state].some((v) => v?.toLowerCase().includes(q)),
        )
      : d.stores;
    return [...filtered].sort((a, b) => {
      const x = sortValue(a, sort.key);
      const y = sortValue(b, sort.key);
      const order = x < y ? -1 : x > y ? 1 : 0;
      return sort.desc ? -order : order;
    });
  }, [d.stores, query, sort]);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2 sm:max-w-xs">
        <Label htmlFor="store-search">Find a location</Label>
        <Input
          id="store-search"
          type="search"
          placeholder="Store number, name, or city"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <p className="text-sm text-muted-foreground">
        {integer.format(rows.length)} of {integer.format(d.stores.length)} locations
      </p>
      <div className="overflow-x-auto rounded-lg border border-border bg-card">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b border-border text-left">
              {COLUMNS.map((c) => {
                const active = sort.key === c.key;
                return (
                  <th
                    key={c.key}
                    scope="col"
                    aria-sort={active ? (sort.desc ? "descending" : "ascending") : "none"}
                    className={c.numeric ? "p-3 text-right" : "p-3"}
                  >
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 font-medium text-muted-foreground hover:text-foreground"
                      onClick={() =>
                        setSort({ key: c.key, desc: active ? !sort.desc : Boolean(c.numeric) })
                      }
                    >
                      {c.label}
                      {active &&
                        (sort.desc ? (
                          <ArrowDown className="size-3" aria-hidden />
                        ) : (
                          <ArrowUp className="size-3" aria-hidden />
                        ))}
                    </button>
                  </th>
                );
              })}
              <th scope="col" className="p-3 text-right font-medium text-muted-foreground">
                Days since
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => {
              const days = daysSince(d.as_of, s.last_service);
              return (
                <tr key={s.location_id} className="border-b border-border last:border-0">
                  <td className="p-3 tabular-nums">{s.store_number ?? "—"}</td>
                  <td className="p-3">
                    <Link
                      href={`/locations/${s.location_id}`}
                      className="text-primary hover:underline"
                    >
                      {s.name ?? `LocationID ${s.pestpac_location_id}`}
                    </Link>
                    <span className="block text-xs text-muted-foreground">
                      {[s.city, s.state].filter(Boolean).join(", ")}
                    </span>
                  </td>
                  <td className="p-3 text-right tabular-nums">{integer.format(s.services)}</td>
                  <td className="p-3 text-right tabular-nums">{integer.format(s.open_orders)}</td>
                  <td className="p-3">{formatDate(s.last_service)}</td>
                  <td className="p-3 text-right tabular-nums">
                    {days === null ? "—" : integer.format(days)}
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={6} className="p-4 text-muted-foreground">
                  No locations match.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** A tab whose data isn't collected yet (docs/customer-dashboard-plan.md). */
function ComingSoon({ title, phase, shows }: { title: string; phase: string; shows: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>Not available yet: {phase}.</CardDescription>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground">{shows}</p>
      </CardContent>
    </Card>
  );
}

const PLACEHOLDERS = [
  {
    value: "activity",
    tab: "Rodent activity",
    phase: "needs the findings sync (plan phase 2)",
    shows:
      "Activity rate by month and program stage, documented captures, where activity was found, and stores with recent activity, from PestPac device pest findings.",
  },
  {
    value: "structural",
    tab: "Structural",
    phase: "needs the findings sync (plan phase 2)",
    shows:
      "Structural findings by type and area, logged vs. remediated by month, and open vulnerabilities, from PestPac conditions.",
  },
  {
    value: "sanitation",
    tab: "Sanitation & pests",
    phase: "needs the findings sync (plan phase 2)",
    shows:
      "Sanitation concerns by type and area, secondary pests, and stores with recurring concerns.",
  },
  {
    value: "tracker",
    tab: "Program tracker",
    phase: "needs programs and enrollments (plan phase 3)",
    shows:
      "Each location's program tier, stage, and milestone dates (launch, inspection, proposal, approval, phases).",
  },
  {
    value: "risk",
    tab: "Risk",
    phase: "needs findings and program metrics (plan phase 4)",
    shows:
      "The program's risk index and bands per location, a portfolio risk map, and the customer's own risk lists alongside field findings.",
  },
] as const;

export function CompanyDashboardView() {
  const { companyId } = useParams<{ companyId: string }>();
  const [tab, setTab] = useUrlTab(
    ["overview", "stores", ...PLACEHOLDERS.map((p) => p.value), "reports"],
    "overview",
  );
  const { can } = usePermissions();
  const [billToId, setBillToId] = useState("");
  const company = useCompaniesGetCompany(companyId);
  const billTos = useCompaniesListBillTos(companyId);
  useDocumentTitle("Dashboard", company.data?.data.name);
  const dashboard = useDashboardGetCompanyDashboard(
    companyId,
    billToId ? { bill_to_id: billToId } : undefined,
  );

  if (company.isError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{errorMessage(company.error, "Company not found.")}</AlertDescription>
      </Alert>
    );
  }
  const c = company.data?.data;

  return (
    <div className="flex flex-col gap-6">
      <div>
        {c && <Breadcrumbs trail={[...c.trail, { kind: "company", id: c.id, name: c.name }]} />}
        <h1 className="mt-2 text-3xl">{c ? `${c.name} dashboard` : "Dashboard"}</h1>
        <p className="text-muted-foreground">
          Service activity from PestPac
          {dashboard.data && ` · as of ${new Date(dashboard.data.data.as_of).toLocaleString()}`}
        </p>
      </div>

      <div className="flex flex-col gap-2 sm:max-w-sm">
        <Label htmlFor="dashboard-bill-to">Bill-to</Label>
        <NativeSelect
          id="dashboard-bill-to"
          className="w-full"
          value={billToId}
          onChange={(e) => setBillToId(e.target.value)}
        >
          <NativeSelectOption value="">All bill-tos</NativeSelectOption>
          {billTos.data?.data.map((b) => (
            <NativeSelectOption key={b.id} value={b.id}>
              {b.name}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </div>

      {dashboard.isPending && <p className="text-muted-foreground">Loading…</p>}
      {dashboard.isError && (
        <Alert variant="destructive">
          <AlertDescription>
            {errorMessage(dashboard.error, "Could not load the dashboard.")}
          </AlertDescription>
        </Alert>
      )}
      {dashboard.data && (
        <Tabs value={tab} onValueChange={setTab}>
          <div className="overflow-x-auto">
            <TabsList>
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="stores">Stores</TabsTrigger>
              {PLACEHOLDERS.map((p) => (
                <TabsTrigger key={p.value} value={p.value}>
                  {p.tab}
                </TabsTrigger>
              ))}
              {c && can("reports:read", c.operator_id) && (
                <TabsTrigger value="reports">Reports</TabsTrigger>
              )}
            </TabsList>
          </div>
          <TabsContent value="overview" className="pt-4">
            <Overview d={dashboard.data.data} />
          </TabsContent>
          <TabsContent value="stores" className="pt-4">
            <Stores d={dashboard.data.data} />
          </TabsContent>
          {PLACEHOLDERS.map((p) => (
            <TabsContent key={p.value} value={p.value} className="pt-4">
              <ComingSoon title={p.tab} phase={p.phase} shows={p.shows} />
            </TabsContent>
          ))}
          {c && can("reports:read", c.operator_id) && (
            <TabsContent value="reports" className="flex flex-col gap-3 pt-4">
              <ReportTemplatesSection companyId={companyId} operatorId={c.operator_id} />
              <p className="text-sm text-muted-foreground">
                Download a report from a location&apos;s page (Stores tab → location).
              </p>
            </TabsContent>
          )}
        </Tabs>
      )}
    </div>
  );
}
