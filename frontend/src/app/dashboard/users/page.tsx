import type { Metadata } from "next";
import { UsersView } from "@/features/users/users-view";

export const instant = false;

export const metadata: Metadata = { title: "User Management" };

export default function UsersPage() {
  return <UsersView />;
}
