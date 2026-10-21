import { Suspense } from "react";

import { BrandBand, ProofPoints } from "@/components/brand";
import { LoginForm } from "@/components/login-form";

export default function LoginPage() {
  return (
    <main className="grid flex-1 lg:grid-cols-2">
      <BrandBand title="Big enough to back you, small enough to know you" className="lg:py-20">
        <p>Sign in to manage your Select Exterminating portal.</p>
        <ProofPoints />
      </BrandBand>
      <div className="flex items-center justify-center bg-muted px-6 py-16">
        <Suspense>
          <LoginForm />
        </Suspense>
      </div>
    </main>
  );
}
