import { redirect } from "next/navigation";

// V3/V4 address. Runs now live in Activity: /runs?run=<id> → /activity/<id>.
export default async function OldRuns({ searchParams }: { searchParams: Promise<{ run?: string }> }) {
  const { run } = await searchParams;
  redirect(run ? `/activity/${encodeURIComponent(run)}` : "/activity");
}
