"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  getItemsListItemsQueryKey,
  useItemsCreateItem,
  useItemsListItems,
} from "@/lib/api/generated/items/items";

const schema = z.object({ name: z.string().trim().min(1, "Name is required").max(200) });
type FormValues = z.infer<typeof schema>;

export function ItemsPanel() {
  const queryClient = useQueryClient();
  const items = useItemsListItems();
  const create = useItemsCreateItem({
    mutation: {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: getItemsListItemsQueryKey() }),
    },
  });
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  const onSubmit = async (values: FormValues) => {
    await create.mutateAsync({ data: values });
    reset();
  };

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Add item</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit(onSubmit)} className="flex items-end gap-3" noValidate>
            <div className="flex flex-1 flex-col gap-2">
              <Label htmlFor="item-name">Name</Label>
              <Input id="item-name" {...register("name")} />
              {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
            </div>
            <Button type="submit" disabled={create.isPending}>
              Add
            </Button>
          </form>
          {create.isError && (
            <Alert variant="destructive" className="mt-4">
              <AlertDescription>Could not create the item.</AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

      {items.isPending && <p className="text-muted-foreground">Loading…</p>}
      {items.isError && (
        <Alert variant="destructive">
          <AlertDescription>Could not load items.</AlertDescription>
        </Alert>
      )}
      {items.data && (
        <ul className="divide-y divide-border rounded-lg border border-border bg-card">
          {items.data.data.length === 0 && (
            <li className="p-4 text-muted-foreground">No items yet.</li>
          )}
          {items.data.data.map((item) => (
            <li key={item.id} className="flex items-center justify-between p-4">
              <span>{item.name}</span>
              <span className="text-sm text-muted-foreground">{item.status}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
