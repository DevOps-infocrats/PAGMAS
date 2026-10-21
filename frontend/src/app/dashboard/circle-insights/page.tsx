import type { Metadata } from "next";
import { CircleInsightsView } from "@/features/circle-insights/circle-insights-view";

export const instant = false;

export const metadata: Metadata = { title: "Circle Insights" };

export default function CircleInsightsPage() {
  return <CircleInsightsView />;
}
