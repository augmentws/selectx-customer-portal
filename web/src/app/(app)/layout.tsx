import { Suspense } from "react";

import { AppHeader } from "@/components/app-header";
import { SessionGate } from "@/components/session-gate";

export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="flex flex-1 flex-col bg-muted">
      <AppHeader />
      <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-10">
        {/* SessionGate reads the URL, which is only known at request time. */}
        <Suspense fallback={<p className="text-muted-foreground">Loading…</p>}>
          <SessionGate>{children}</SessionGate>
        </Suspense>
      </main>
    </div>
  );
}
