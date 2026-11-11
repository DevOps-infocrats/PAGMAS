import Link from "next/link";
import { Logo } from "@/components/brand/logo";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils/cn";

export default function NotFound() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-5">
      <div className="w-full max-w-md rounded-xl border border-border bg-card p-8 text-center shadow-sm">
        <Logo variant="wordmark" width={120} eager className="mx-auto" />
        <p className="mt-6 text-sm font-semibold uppercase tracking-wider text-muted-foreground">404</p>
        <h1 className="mt-1 text-xl font-semibold text-heading">This page could not be found</h1>
        <p className="mt-2 text-sm text-muted-foreground">The address may be mistyped or out of date. Open the dashboard and use the menu on the left.</p>
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <Link href="/dashboard" className={cn(buttonVariants({ variant: "primary" }))}>
            Go to dashboard
          </Link>
          <Link href="/dashboard/tickets/user" className={cn(buttonVariants({ variant: "outline" }))}>
            User Tickets
          </Link>
        </div>
      </div>
    </main>
  );
}
