import type { Metadata } from "next";
import { AdminTicketsView } from "@/features/tickets/admin-tickets-view";

export const instant = false;

export const metadata: Metadata = { title: "Admin Tickets" };

export default function AdminTicketsPage() {
  return <AdminTicketsView />;
}
