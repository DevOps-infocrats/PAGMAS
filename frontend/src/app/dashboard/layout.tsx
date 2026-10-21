import { Suspense } from "react";
import { PageSkeleton } from "@/components/feedback/states";
import { AppShell } from "@/components/layout/app-shell";
import { ClientGate } from "@/components/layout/client-gate";
import { DataProvider } from "@/components/providers/data-provider";
import { SessionProvider } from "@/components/providers/session-provider";

// Authenticated, client-rendered area: data is fetched per session from the API,
// so instant-navigation (static shell) validation does not apply here.
export const instant = false;

const shellFallback = (
  <div className="mx-auto max-w-[1600px] px-4 py-8 lg:px-8">
    <PageSkeleton />
  </div>
);

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <DataProvider>
        <ClientGate fallback={shellFallback}>
          <Suspense fallback={shellFallback}>
            <AppShell>{children}</AppShell>
          </Suspense>
        </ClientGate>
      </DataProvider>
    </SessionProvider>
  );
}
