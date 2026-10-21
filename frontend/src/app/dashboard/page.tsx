import type { Metadata } from "next";
import { OverviewView } from "@/features/overview/overview-view";

export const instant = false;

export const metadata: Metadata = { title: "Circle Overview" };

export default function CircleOverviewPage() {
  return <OverviewView />;
}
