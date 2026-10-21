"use client";

import { ShieldAlert } from "lucide-react";
import { EmptyState } from "@/components/feedback/states";
import { Card } from "@/components/ui/primitives";
import { useSession } from "@/hooks/use-session";

/**
 * UI-level guard for admin pages. The real enforcement is server-side: every
 * admin API endpoint requires the admin role (HTTP 403 otherwise).
 */
export function AdminGuard({ children }: { children: React.ReactNode }) {
  const { session, isAdmin, loading } = useSession();
  if (loading || !session) return null;
  if (!isAdmin)
    return (
      <Card>
        <EmptyState icon={ShieldAlert} title="Admins only" description="This page is available to admin accounts only." />
      </Card>
    );
  return <>{children}</>;
}
