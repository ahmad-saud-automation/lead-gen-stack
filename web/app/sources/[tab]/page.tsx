import { SourcePage } from "@/components/leads/source";

export const metadata = { title: "Lead source · Lead Gen Engine" };

// [tab] is a sheet tab name, a local file's name or an upload (import:<name>), URL-encoded.
export default async function SourceRoute({ params }: { params: Promise<{ tab: string }> }) {
  const { tab } = await params;
  return <SourcePage tab={decodeURIComponent(tab)} />;
}
