import type { Metadata } from "next";
import { UserTicketsView } from "@/features/tickets/user-tickets-view";

export const instant = false;

export const metadata: Metadata = { title: "User Tickets" };

export default function UserTicketsPage() {
  return <UserTicketsView />;
}
