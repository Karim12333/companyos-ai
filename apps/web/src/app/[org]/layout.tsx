import { OrgShell } from "@/components/app-shell";

export default function OrgLayout({ children }: LayoutProps<"/[org]">) {
  return <OrgShell>{children}</OrgShell>;
}
