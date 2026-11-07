import { CampaignPage } from "@/components/campaign/page";

export const metadata = { title: "Campaign · Lead Gen Engine" };

export default async function CampaignRoute({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <CampaignPage id={decodeURIComponent(id)} />;
}
