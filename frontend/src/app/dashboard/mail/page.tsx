import type { Metadata } from "next";
import { MailView } from "@/features/mail/mail-view";

export const instant = false;

export const metadata: Metadata = { title: "Mail Configuration" };

export default function MailPage() {
  return <MailView />;
}
