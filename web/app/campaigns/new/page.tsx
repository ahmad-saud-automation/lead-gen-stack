import { NewCampaignWizard } from "@/components/campaign/wizard";

export const metadata = { title: "New campaign · Lead Gen Engine" };

// ?tab=<source> starts the wizard on that lead source (from a source's "Create a campaign from it").
export default async function NewCampaignRoute({ searchParams }: { searchParams: Promise<{ tab?: string }> }) {
  const { tab } = await searchParams;
  return <NewCampaignWizard presetTab={tab} />;
}
