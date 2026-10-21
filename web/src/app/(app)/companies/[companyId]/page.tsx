import { CompanyDetail } from "@/components/company-detail";

// The id is read client-side with useParams(); see operators/[operatorId]/page.tsx.
export default function CompanyPage() {
  return <CompanyDetail />;
}
