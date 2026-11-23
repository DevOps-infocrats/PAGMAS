import { Ban, Boxes, CalendarRange, ClipboardCheck, FileBarChart2, KeyRound, Mail, PhoneCall, Target, Ticket, LayoutDashboard, Map, MapPin, ServerCog, Settings, Users, type LucideIcon } from "lucide-react";
import type { PageKey } from "@/lib/api";

export interface NavItem {
  label: string;
  /** Sidebar text when the full label would wrap (the full label stays in tooltips and search) */
  shortLabel?: string;
  href: string;
  icon: LucideIcon;
  adminOnly?: boolean;
  /** Roles & Access: the role page this entry opens (shown only when the user's role shows it on this device) */
  pageKey?: PageKey;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

export const NAV: NavGroup[] = [
  {
    label: "Overview",
    items: [{ label: "Circle Overview", href: "/dashboard", icon: LayoutDashboard, pageKey: "overview" }],
  },
  {
    label: "Network Insights",
    items: [
      { label: "Circle Insights", href: "/dashboard/circle-insights", icon: Map, pageKey: "circle-insights" },
      { label: "Block Insights", href: "/dashboard/block-insights", icon: Boxes, pageKey: "block-insights" },
      { label: "GP Insights", href: "/dashboard/gp-insights", icon: MapPin, pageKey: "gp-insights" },
    ],
  },
  {
    label: "Field Operations",
    items: [
      { label: "AMC Conversion Plan vs Execution", shortLabel: "AMC Conversion", href: "/dashboard/amc-conversion", icon: Target, pageKey: "amc-conversion" },
      { label: "Field Team & Escalation", href: "/dashboard/field-team", icon: PhoneCall, pageKey: "field-team" },
    ],
  },
  {
    label: "Reporting",
    items: [{ label: "Management Review", href: "/dashboard/reports", icon: FileBarChart2, pageKey: "reports" }],
  },
  {
    // Admins assign and review work; every user sees the tickets assigned to them (rules enforced by the backend).
    label: "Ticket Management",
    items: [
      { label: "Admin Tickets", href: "/dashboard/tickets/admin", icon: ClipboardCheck, adminOnly: true },
      { label: "Ticket Report", href: "/dashboard/tickets/report", icon: CalendarRange, adminOnly: true },
      { label: "User Tickets", href: "/dashboard/tickets/user", icon: Ticket, pageKey: "tickets-user" },
      { label: "Non-Doable Cases", href: "/dashboard/tickets/non-doable", icon: Ban, pageKey: "tickets-nondoable" },
    ],
  },
  {
    label: "Administration",
    items: [
      { label: "Data Operations", href: "/dashboard/operations", icon: ServerCog, adminOnly: true },
      { label: "User Management", href: "/dashboard/users", icon: Users, adminOnly: true },
      { label: "Roles & Access", href: "/dashboard/roles", icon: KeyRound, adminOnly: true },
      { label: "Mail Configuration", href: "/dashboard/mail", icon: Mail, adminOnly: true },
      { label: "Settings", href: "/dashboard/settings", icon: Settings, adminOnly: true },
    ],
  },
];

export const ALL_NAV_ITEMS = NAV.flatMap((g) => g.items);

export function isActive(pathname: string, href: string) {
  return href === "/dashboard" ? pathname === "/dashboard" : pathname.startsWith(href);
}
