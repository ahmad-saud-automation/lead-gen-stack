import { redirect } from "next/navigation";

// V4 address. History is now Activity.
export default function OldHistory() {
  redirect("/activity");
}
