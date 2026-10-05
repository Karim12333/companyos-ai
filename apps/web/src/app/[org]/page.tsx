import { redirect } from "next/navigation";

export default async function OrgIndex({ params }: PageProps<"/[org]">) {
  const { org } = await params;
  redirect(`/${org}/headquarters`);
}
