import type { Metadata } from "next";
import { ManagementReviewView } from "@/features/review/review-view";

export const instant = false;

export const metadata: Metadata = { title: "Management Review" };

export default function ReportsPage() {
  return <ManagementReviewView />;
}
