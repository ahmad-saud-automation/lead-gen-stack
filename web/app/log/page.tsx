import { redirect } from "next/navigation";

// V4 address. The log is now Activity's search and each run's "Step by step" tab.
export default function OldLog() {
  redirect("/activity");
}
