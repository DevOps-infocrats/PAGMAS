import type { Metadata } from "next";
import { OperationsView } from "@/features/operations/operations-view";

export const instant = false;

export const metadata: Metadata = { title: "Data Operations" };

export default function OperationsPage() {
  return <OperationsView />;
}
