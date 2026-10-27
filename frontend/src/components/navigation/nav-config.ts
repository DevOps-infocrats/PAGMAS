import { Boxes, FileBarChart2, Mail, PhoneCall, Target, LayoutDashboard, Map, MapPin, ServerCog, Settings, Users, type LucideIcon } from "lucide-react";

export interface NavItem {
  label: string;
  /** Sidebar text when the full label would wrap (the full label stays in tooltips and search) */
  shortLabel?: string;
  href: string;
  icon: LucideIcon;
  adminOnly?: boolean;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

export const NAV: NavGroup[] = [
  {
    label: "Overview",
    items: [{ label: "Circle Overview", href: "/dashboard", icon: LayoutDashboard }],
  },
  {
    label: "Network Insights",
    items: [
      { label: "Circle Insights", href: "/dashboard/circle-insights", icon: Map },
      { label: "Block Insights", href: "/dashboard/block-insights", icon: Boxes },
      { label: "GP Insights", href: "/dashboard/gp-insights", icon: MapPin },
    ],
  },
  {
    label: "Field Operations",
    items: [
      { label: "AMC Conversion Plan vs Execution", shortLabel: "AMC Conversion", href: "/dashboard/amc-conversion", icon: Target },
      { label: "Field Team & Escalation", href: "/dashboard/field-team", icon: PhoneCall },
    ],
  },
  {
    label: "Reporting",
    items: [{ label: "Management Review", href: "/dashboard/reports", icon: FileBarChart2 }],
  },
  {
    label: "Administration",
    items: [
      { label: "Data Operations", href: "/dashboard/operations", icon: ServerCog, adminOnly: true },
      { label: "User Management", href: "/dashboard/users", icon: Users, adminOnly: true },
      { label: "Mail Configuration", href: "/dashboard/mail", icon: Mail, adminOnly: true },
      { label: "Settings", href: "/dashboard/settings", icon: Settings, adminOnly: true },
    ],
  },
];

export const ALL_NAV_ITEMS = NAV.flatMap((g) => g.items);

export function isActive(pathname: string, href: string) {
  return href === "/dashboard" ? pathname === "/dashboard" : pathname.startsWith(href);
}
