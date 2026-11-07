import { redirect } from "next/navigation";

/* The old "Live demo" page (2026-11-06) is replaced by Pipeline run; an old link lands there. */
export default function OldDemoRoute() {
  redirect("/pipeline");
}
