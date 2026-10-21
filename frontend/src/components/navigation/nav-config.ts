import { Boxes, FileBarChart2, PhoneCall, Target, LayoutDashboard, Map, MapPin, ServerCog, Settings, type LucideIcon } from "lucide-react";

export interface NavItem {
  label: string;
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
    label: "Analytics",
    items: [
      { label: "Circle Overview", href: "/dashboard", icon: LayoutDashboard },
      { label: "Circle Insights", href: "/dashboard/circle-insights", icon: Map },
      { label: "Block Insights", href: "/dashboard/block-insights", icon: Boxes },
      { label: "GP Insights", href: "/dashboard/gp-insights", icon: MapPin },
      { label: "AMC Conversion Plan vs Execution", href: "/dashboard/amc-conversion", icon: Target },
      { label: "Field Team & Escalation", href: "/dashboard/field-team", icon: PhoneCall },
    ],
  },
  {
    label: "Reporting",
    items: [{ label: "Management Review", href: "/dashboard/reports", icon: FileBarChart2 }],
  },
  {
    label: "Admin",
    items: [
      { label: "Data Operations", href: "/dashboard/operations", icon: ServerCog, adminOnly: true },
      { label: "Settings", href: "/dashboard/settings", icon: Settings, adminOnly: true },
    ],
  },
];

export const ALL_NAV_ITEMS = NAV.flatMap((g) => g.items);

export function isActive(pathname: string, href: string) {
  return href === "/dashboard" ? pathname === "/dashboard" : pathname.startsWith(href);
}
