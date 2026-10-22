import { CompanyDashboardView } from "@/components/company-dashboard";

// The id is read client-side with useParams(); see operators/[operatorId]/page.tsx.
export default function CompanyDashboardPage() {
  return <CompanyDashboardView />;
}
