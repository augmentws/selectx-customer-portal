import Image from "next/image";
import Link from "next/link";

import { cn } from "@/lib/utils";

// The logo has black lettering on transparency: place it on light surfaces only.
export function BrandLogo({ className, href = "/" }: { className?: string; href?: string }) {
  return (
    <Link href={href} className={cn("inline-flex shrink-0", className)}>
      <Image
        src="/brand/select-exterminating-logo.webp"
        alt="Select Exterminating"
        width={768}
        height={214}
        priority
        className="h-8 w-auto"
      />
    </Link>
  );
}

/** Black statement band with a gold rule (docs/design-guidance.md §3, §6). */
export function BrandBand({
  title,
  children,
  className,
}: {
  title: string;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn(
        "flex flex-col justify-center bg-ink px-8 py-12 text-white sm:px-12",
        className,
      )}
    >
      <h1 className="max-w-md text-4xl sm:text-5xl">{title}</h1>
      <div aria-hidden className="mt-6 h-1 w-16 bg-highlight" />
      {children && <div className="mt-6 max-w-md text-lg leading-relaxed">{children}</div>}
    </section>
  );
}

export function ProofPoints() {
  return (
    <dl className="mt-10 grid grid-cols-3 gap-6">
      {[
        ["70+", "Years in business"],
        ["9", "Branches"],
        ["900+", "Technicians"],
      ].map(([value, label]) => (
        <div key={label}>
          <dt className="sr-only">{label}</dt>
          <dd className="font-heading text-3xl font-bold text-highlight">{value}</dd>
          <dd className="text-sm">{label}</dd>
        </div>
      ))}
    </dl>
  );
}
