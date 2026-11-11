import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";

/** "‹ Back to …" button of the Insights title bars (see useInsightsNav); renders nothing without a target. */
export function BackLink({ back }: { back: { href: string; label: string } | null }) {
  if (!back) return null;
  return (
    <Link href={back.href} className={buttonVariants({ variant: "outline" })}>
      <ChevronLeft aria-hidden /> {back.label}
    </Link>
  );
}
