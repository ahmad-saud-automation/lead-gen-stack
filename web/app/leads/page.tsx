import { LeadsPage } from "@/components/stack/leads";

export const metadata = { title: "Leads · Lead Gen Engine" };

// The lead sources list that lived here moved to /sources (2026-11-06).
export default function LeadsRoute() {
  return <LeadsPage />;
}
