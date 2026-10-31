"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { errorMessage } from "@/lib/api/errors";
import {
  getAreaMappingListAreaTypesQueryKey,
  getAreaMappingListZonesQueryKey,
  useAreaMappingListAreaTypes,
  useAreaMappingListZones,
  useAreaMappingSetZoneName,
  useAreaMappingSyncAreaTypes,
  useAreaMappingUpdateAreaType,
} from "@/lib/api/generated/area-mapping/area-mapping";
import type { AreaTypeSyncRead, Zone, ZoneRead } from "@/lib/api/generated/model";
import { usePermissions } from "@/lib/permissions";

/** The operator's area mapping: display names for the fixed zones, and the zone each PestPac
 * area type counts as. Editing needs bill_tos:write. */
export function AreaMappingPanel({ operatorId }: { operatorId: string }) {
  const { can } = usePermissions();
  const canWrite = can("bill_tos:write", operatorId);
  const zones = useAreaMappingListZones(operatorId);

  if (zones.isPending) return <p className="text-muted-foreground">Loading…</p>;
  if (zones.isError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{errorMessage(zones.error, "Could not load zones.")}</AlertDescription>
      </Alert>
    );
  }
  return (
    <div className="flex flex-col gap-6">
      <AreaTypes operatorId={operatorId} zones={zones.data.data} canWrite={canWrite} />
      <Zones operatorId={operatorId} zones={zones.data.data} canWrite={canWrite} />
    </div>
  );
}

function AreaTypes({
  operatorId,
  zones,
  canWrite,
}: {
  operatorId: string;
  zones: ZoneRead[];
  canWrite: boolean;
}) {
  const queryClient = useQueryClient();
  const types = useAreaMappingListAreaTypes(operatorId);
  const [synced, setSynced] = useState<AreaTypeSyncRead | null>(null);
  const refetch = () =>
    queryClient.invalidateQueries({ queryKey: getAreaMappingListAreaTypesQueryKey(operatorId) });
  const sync = useAreaMappingSyncAreaTypes({
    mutation: {
      onSuccess: (res) => {
        setSynced(res.data);
        refetch();
      },
    },
  });
  const update = useAreaMappingUpdateAreaType({ mutation: { onSuccess: refetch } });

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3">
        <div>
          <CardTitle>PestPac area types</CardTitle>
          <p className="text-sm text-muted-foreground">
            The zone each type&apos;s areas count as. Areas with no type, or an unmapped one, get no
            zone; findings read from notes get theirs from the notes.
          </p>
        </div>
        {canWrite && (
          <Button
            variant="outline"
            disabled={sync.isPending}
            onClick={() => sync.mutate({ operatorId })}
          >
            {sync.isPending ? "Syncing…" : "Sync from PestPac"}
          </Button>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {sync.isError && (
          <Alert variant="destructive">
            <AlertDescription>
              {errorMessage(sync.error, "Could not sync area types.")}
            </AlertDescription>
          </Alert>
        )}
        {synced && (
          <p className="text-sm text-muted-foreground">
            Synced {synced.total} types: {synced.added} new, {synced.removed} no longer listed.
          </p>
        )}
        {update.isError && (
          <Alert variant="destructive">
            <AlertDescription>{errorMessage(update.error, "Could not save.")}</AlertDescription>
          </Alert>
        )}
        {types.isPending ? (
          <p className="text-muted-foreground">Loading…</p>
        ) : types.isError ? (
          <Alert variant="destructive">
            <AlertDescription>
              {errorMessage(types.error, "Could not load area types.")}
            </AlertDescription>
          </Alert>
        ) : types.data.data.length === 0 ? (
          <p className="text-muted-foreground">
            No area types yet. Sync them from PestPac to map them to zones.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-muted-foreground">
                <tr className="border-b border-border">
                  <th className="py-2 pr-4 font-medium">Code</th>
                  <th className="py-2 pr-4 font-medium">Description</th>
                  <th className="py-2 pr-4 text-right font-medium">Areas</th>
                  <th className="py-2 font-medium">Zone</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {types.data.data.map((t) => (
                  <tr key={t.id}>
                    <td className="py-2 pr-4 font-medium">{t.code}</td>
                    <td className="py-2 pr-4">{t.description ?? "—"}</td>
                    <td className="py-2 pr-4 text-right">{t.areas}</td>
                    <td className="py-2">
                      {canWrite ? (
                        <NativeSelect
                          aria-label={`Zone for ${t.code}`}
                          value={t.zone ?? ""}
                          disabled={update.isPending}
                          onChange={(e) =>
                            update.mutate({
                              areaTypeId: t.id,
                              data: { zone: (e.target.value || null) as Zone | null },
                            })
                          }
                        >
                          <NativeSelectOption value="">Not mapped</NativeSelectOption>
                          {zones.map((z) => (
                            <NativeSelectOption key={z.zone} value={z.zone}>
                              {z.display_name}
                            </NativeSelectOption>
                          ))}
                        </NativeSelect>
                      ) : (
                        (t.zone_name ?? <span className="text-muted-foreground">Not mapped</span>)
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Zones({
  operatorId,
  zones,
  canWrite,
}: {
  operatorId: string;
  zones: ZoneRead[];
  canWrite: boolean;
}) {
  const queryClient = useQueryClient();
  const save = useAreaMappingSetZoneName({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getAreaMappingListZonesQueryKey(operatorId) });
        // Area types show their zone's name.
        queryClient.invalidateQueries({
          queryKey: getAreaMappingListAreaTypesQueryKey(operatorId),
        });
      },
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Zones</CardTitle>
        <p className="text-sm text-muted-foreground">
          The fixed zones findings, areas, and dashboards group by, with the names shown for this
          operator. Clear a name to restore the default.
        </p>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {save.isError && (
          <Alert variant="destructive">
            <AlertDescription>{errorMessage(save.error, "Could not save.")}</AlertDescription>
          </Alert>
        )}
        <ul className="divide-y divide-border">
          {zones.map((z) => (
            <li key={z.zone} className="grid items-center gap-2 py-2 text-sm sm:grid-cols-2">
              <div>
                <div className="font-medium">{z.default_name}</div>
                <div className="text-xs text-muted-foreground">{z.zone}</div>
              </div>
              {canWrite ? (
                <Input
                  // Remount when the saved name changes, so the field shows it.
                  key={z.display_name}
                  aria-label={`Display name for ${z.default_name}`}
                  defaultValue={z.display_name === z.default_name ? "" : z.display_name}
                  placeholder={z.default_name}
                  maxLength={100}
                  onBlur={(e) => {
                    const name = e.target.value.trim();
                    const current = z.display_name === z.default_name ? "" : z.display_name;
                    if (name !== current) {
                      save.mutate({
                        operatorId,
                        zone: z.zone,
                        data: { display_name: name || null },
                      });
                    }
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") e.currentTarget.blur();
                  }}
                />
              ) : (
                <span>{z.display_name}</span>
              )}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
