import { redirect } from "next/navigation";

// V4 address. Uploads and sheet tabs are now on Leads: /import?tab=<tab> → /leads/<tab>.
export default async function OldImport({ searchParams }: { searchParams: Promise<{ tab?: string }> }) {
  const { tab } = await searchParams;
  redirect(tab ? `/sources/${encodeURIComponent(tab)}` : "/sources");
}
