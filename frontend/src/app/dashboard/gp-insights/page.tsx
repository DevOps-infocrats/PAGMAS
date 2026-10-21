import type { Metadata } from "next";
import { GpInsightsView } from "@/features/gp-insights/gp-insights-view";

export const instant = false;

export const metadata: Metadata = { title: "GP Insights" };

export default function GpInsightsPage() {
  return <GpInsightsView />;
}
