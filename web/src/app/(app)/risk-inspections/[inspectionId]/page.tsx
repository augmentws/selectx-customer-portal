import { RiskInspectionReport } from "@/components/risk-inspection-report";

// The id is read client-side with useParams(); see operators/[operatorId]/page.tsx.
export default function RiskInspectionPage() {
  return <RiskInspectionReport />;
}
