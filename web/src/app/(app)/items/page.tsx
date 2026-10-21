import { ItemsPanel } from "@/components/items-panel";

export default function ItemsPage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Items</h1>
        <p className="text-muted-foreground">Sample resource served by FastAPI through the BFF.</p>
      </div>
      <ItemsPanel />
    </div>
  );
}
