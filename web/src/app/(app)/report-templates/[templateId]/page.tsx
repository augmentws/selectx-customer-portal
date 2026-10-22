import { EditReportTemplate } from "@/components/report-template-editor";

// The id is read client-side with useParams(); see operators/[operatorId]/page.tsx.
export default function ReportTemplatePage() {
  return <EditReportTemplate />;
}
