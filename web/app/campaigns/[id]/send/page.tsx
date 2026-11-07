import { BacklogSend } from "@/components/campaign/backlog";

export const metadata = { title: "Send waiting leads · Lead Gen Engine" };

export default async function BacklogRoute({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <BacklogSend id={decodeURIComponent(id)} />;
}
