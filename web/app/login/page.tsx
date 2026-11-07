import { LoginForm } from "@/components/login-form";

export const metadata = { title: "Sign in · Lead Gen Engine" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const { next } = await searchParams;
  // only a path on this site, never an address elsewhere
  const safe = next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
  return (
    <div className="page login-page">
      <LoginForm next={safe} />
    </div>
  );
}
