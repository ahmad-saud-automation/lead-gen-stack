import { RecipeEditor } from "@/components/recipe/editor";

export const metadata = { title: "Finding recipe · Lead Gen Engine" };

export default async function RecipeRoute({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <RecipeEditor id={decodeURIComponent(id)} />;
}
