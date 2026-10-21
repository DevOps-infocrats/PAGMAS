import type { Metadata } from "next";
import { KpiListView } from "@/features/kpi-list/kpi-list-view";

export const instant = false;

export const metadata: Metadata = { title: "KPI list" };

export default function KpiListPage() {
  return <KpiListView />;
}
