import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";

export default function HomePage() {
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center gap-6 px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">Customer Portal</h1>
      <p className="text-muted-foreground">
        Sign in to view your account. This is the starter shell: a protected sample page backed
        by the FastAPI <code>/v1/items</code> resource.
      </p>
      <div>
        <Link href="/items" className={buttonVariants()}>
          Go to the portal
        </Link>
      </div>
    </main>
  );
}
