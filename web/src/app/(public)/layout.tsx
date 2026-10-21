import { BrandLogo } from "@/components/brand";

export default function PublicLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="flex flex-1 flex-col">
      <header className="border-b-4 border-highlight bg-background">
        <div className="flex h-20 items-center px-8 sm:px-12">
          <BrandLogo className="[&_img]:h-11" />
        </div>
      </header>
      {children}
    </div>
  );
}
