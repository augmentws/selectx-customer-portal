import { ServiceReportEditor } from "@/components/service-report";

// The id is read client-side with useParams(); see operators/[operatorId]/page.tsx.
export default function ServiceReportPage() {
  return <ServiceReportEditor />;
}
