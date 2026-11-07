import { redirect } from "next/navigation";

// V3 address. The plan's counts are now on the Campaigns list and each campaign's Who section.
export default function OldPlan() {
  redirect("/campaigns");
}
