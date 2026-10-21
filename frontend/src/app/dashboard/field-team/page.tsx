import type { Metadata } from "next";
import { FieldTeamView } from "@/features/field-team/field-team-view";

export const instant = false;

export const metadata: Metadata = { title: "Field Team & Escalation" };

export default function FieldTeamPage() {
  return <FieldTeamView />;
}
