import Link from "next/link";

import { BrandBand, ProofPoints } from "@/components/brand";
import { buttonVariants } from "@/components/ui/button";

export default function HomePage() {
  return (
    <main className="flex flex-1 flex-col">
      <BrandBand title="We lead the Northeast in pest control">
        <p>The Select Exterminating customer portal.</p>
        <ProofPoints />
      </BrandBand>
      <div className="px-8 py-12 sm:px-12">
        <Link href="/operators" className={buttonVariants({ size: "lg" })}>
          Sign in to the portal
        </Link>
      </div>
    </main>
  );
}
