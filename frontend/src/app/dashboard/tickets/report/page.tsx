import type { Metadata } from "next";
import { TicketReportView } from "@/features/tickets/ticket-report-view";

export const instant = false;

export const metadata: Metadata = { title: "Ticket Report" };

export default function TicketReportPage() {
  return <TicketReportView />;
}
