import type { Metadata } from "next";
import { Lato, Oswald } from "next/font/google";

import { Providers } from "@/components/providers";

import "./globals.css";

// Brand type: Oswald for headlines, Lato for everything else (docs/design-guidance.md §4).
const oswald = Oswald({ variable: "--font-oswald", subsets: ["latin"], weight: ["500", "700"] });
const lato = Lato({ variable: "--font-lato", subsets: ["latin"], weight: ["400", "700"] });

export const metadata: Metadata = {
  title: "Customer Portal · Select Exterminating",
  description: "Select Exterminating customer portal",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${oswald.variable} ${lato.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col bg-background text-base text-foreground">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
