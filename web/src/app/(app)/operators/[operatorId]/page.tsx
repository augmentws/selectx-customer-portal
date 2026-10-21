import { OperatorDetail } from "@/components/operator-detail";

// The id is read client-side with useParams(); awaiting `params` here would hold the
// prerendered shell open under Cache Components.
export default function OperatorPage() {
  return <OperatorDetail />;
}
