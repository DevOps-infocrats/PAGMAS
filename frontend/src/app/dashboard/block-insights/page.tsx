import type { Metadata } from "next";
import { BlockInsightsView } from "@/features/block-insights/block-insights-view";

export const instant = false;

export const metadata: Metadata = { title: "Block Insights" };

export default function BlockInsightsPage() {
  return <BlockInsightsView />;
}
