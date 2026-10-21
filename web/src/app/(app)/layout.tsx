import { AppHeader } from "@/components/app-header";

export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="flex flex-1 flex-col">
      <AppHeader />
      <main className="mx-auto w-full max-w-4xl flex-1 px-6 py-10">{children}</main>
    </div>
  );
}
