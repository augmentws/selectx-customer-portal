"use client";

import {
  Tabs as TabsRoot,
  TabsContent,
  TabsList as UiTabsList,
  TabsTrigger as UiTabsTrigger,
} from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

/**
 * The app's tabs: shadcn's "line" style (an underline, not a raised box) with brand colours.
 * Inactive tabs use muted-foreground, which passes AA on Paper and white (the primitive's
 * foreground at 60% does not); the active tab is body text with a Forest underline.
 */
function TabsList({ className, ...props }: React.ComponentProps<typeof UiTabsList>) {
  return (
    <UiTabsList
      variant="line"
      className={cn("h-auto! w-full justify-start border-b border-border p-0", className)}
      {...props}
    />
  );
}

function TabsTrigger({ className, ...props }: React.ComponentProps<typeof UiTabsTrigger>) {
  return (
    <UiTabsTrigger
      className={cn(
        "flex-none px-3 pt-1.5 pb-2 text-muted-foreground after:bottom-[-1px]! after:bg-primary hover:text-foreground data-active:text-foreground",
        className,
      )}
      {...props}
    />
  );
}

export { TabsRoot as Tabs, TabsContent, TabsList, TabsTrigger };
