import type { Metadata } from "next";
import { AmcConversionView } from "@/features/amc-conversion/amc-conversion-view";

export const instant = false;

export const metadata: Metadata = { title: "AMC Conversion Plan vs Execution" };

export default function AmcConversionPage() {
  return <AmcConversionView />;
}
