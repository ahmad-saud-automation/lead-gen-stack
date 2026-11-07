import { redirect } from "next/navigation";

// V3 address. Column matching now lives on each lead source's page: /fieldmap?tab=<tab> → /leads/<tab>.
export default async function OldFieldmap({ searchParams }: { searchParams: Promise<{ tab?: string }> }) {
  const { tab } = await searchParams;
  redirect(tab ? `/sources/${encodeURIComponent(tab)}` : "/sources");
}
