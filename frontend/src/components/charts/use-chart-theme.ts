"use client";

import { useMemo } from "react";
import { useTheme } from "@/components/providers/theme-provider";

export interface ChartTheme {
  text: string;
  muted: string;
  grid: string;
  axis: string;
  surface: string;
  border: string;
  series: string[];
  good: string;
  warning: string;
  serious: string;
  critical: string;
  na: string;
  font: string;
}

const FALLBACK: ChartTheme = {
  text: "#0e1726",
  muted: "#5b6675",
  grid: "#eceef1",
  axis: "#c9ced6",
  surface: "#ffffff",
  border: "#e4e7ec",
  series: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
  good: "#0ca30c",
  warning: "#fab219",
  serious: "#ec835a",
  critical: "#d03b3b",
  na: "#a3abb6",
  font: "Inter, system-ui, sans-serif",
};

/** Reads chart colours from the CSS tokens so charts follow light/dark theme. */
export function useChartTheme(): ChartTheme {
  const { resolved } = useTheme();
  return useMemo(() => {
    if (typeof window === "undefined") return FALLBACK;
    const cs = getComputedStyle(document.documentElement);
    const v = (name: string, fb: string) => cs.getPropertyValue(name).trim() || fb;
    return {
      text: v("--foreground", FALLBACK.text),
      muted: v("--muted-foreground", FALLBACK.muted),
      grid: v("--chart-grid", FALLBACK.grid),
      axis: v("--chart-axis", FALLBACK.axis),
      surface: v("--card", FALLBACK.surface),
      border: v("--border", FALLBACK.border),
      series: FALLBACK.series.map((fb, i) => v(`--series-${i + 1}`, fb)),
      good: v("--good", FALLBACK.good),
      warning: v("--warning", FALLBACK.warning),
      serious: v("--serious", FALLBACK.serious),
      critical: v("--critical", FALLBACK.critical),
      na: v("--na", FALLBACK.na),
      font: `${v("--font-inter", "Inter")}, system-ui, sans-serif`,
    };
    // `resolved` is the dependency that matters: tokens change with the theme class.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolved]);
}
