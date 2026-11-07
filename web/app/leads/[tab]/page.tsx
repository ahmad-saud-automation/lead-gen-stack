import { redirect } from "next/navigation";

// V5 address. One lead source's page moved to /sources/<tab> on 2026-11-06.
export default async function OldSourceRoute({ params }: { params: Promise<{ tab: string }> }) {
  const { tab } = await params;
  redirect(`/sources/${tab}`);
}
