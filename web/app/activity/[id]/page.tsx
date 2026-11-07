import { RunPage } from "@/components/activity/run";

export const metadata = { title: "Run · Lead Gen Engine" };

// ?tab=send|log opens that tab (the campaign page's "Send found leads" lands on send).
export default async function RunRoute({ params, searchParams }: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ tab?: string }>;
}) {
  const { id } = await params;
  const { tab } = await searchParams;
  return <RunPage id={decodeURIComponent(id)} initialTab={tab} />;
}
