import type { Metadata } from "next";
import { RolesView } from "@/features/roles/roles-view";

export const instant = false;

export const metadata: Metadata = { title: "Roles & Access" };

export default function RolesPage() {
  return <RolesView />;
}
