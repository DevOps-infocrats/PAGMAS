import type { Metadata } from "next";
import { NonDoableView } from "@/features/tickets/non-doable-view";

export const instant = false;

export const metadata: Metadata = { title: "Non-Doable Cases" };

export default function NonDoablePage() {
  return <NonDoableView />;
}
