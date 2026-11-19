"use client";

import { BarChart, LineChart, PieChart } from "echarts/charts";
import { AriaComponent, GridComponent, LegendComponent, MarkAreaComponent, MarkLineComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { LegacyGridContainLabel } from "echarts/features";
import { SVGRenderer } from "echarts/renderers";
import { useEffect, useRef, useState } from "react";

echarts.use([BarChart, LineChart, PieChart, GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, MarkAreaComponent, AriaComponent, SVGRenderer, LegacyGridContainLabel]); // grid.containLabel (axis labels kept inside the chart) needs this in ECharts 6

export type EChartsOption = echarts.EChartsCoreOption;
export interface EChartClickParams {
  name: string;
  dataIndex: number;
  seriesName?: string;
}

/** Below this card width (phones) a chart with many categories scrolls sideways and its legend scrolls. */
const NARROW_PX = 520;
const PX_PER_CATEGORY = 44;

/** Number of categories on a vertical-bar / line chart's x axis (0 = none / not a category axis). */
function xCategories(option: EChartsOption): number {
  const x = (option as { xAxis?: unknown }).xAxis;
  const axis = (Array.isArray(x) ? x[0] : x) as { type?: string; data?: unknown[] } | undefined;
  return axis && axis.type === "category" && Array.isArray(axis.data) ? axis.data.length : 0;
}

/** Phones: a scrollable legend (no overlapping legend rows on a narrow chart). */
function narrowOption(option: EChartsOption): EChartsOption {
  const lg = (option as { legend?: unknown }).legend;
  if (!lg || Array.isArray(lg) || typeof lg !== "object" || (lg as { show?: boolean }).show === false) return option;
  return { ...option, legend: { ...(lg as object), type: "scroll" } };
}

/** Thin React wrapper around ECharts (modular build, SVG renderer). On a narrow card (phone) a chart with many
 * x-axis categories keeps a readable width and scrolls sideways, and the legend scrolls instead of wrapping. */
export function EChart({
  option,
  height = 280,
  ariaLabel,
  onClick,
}: {
  option: EChartsOption;
  height?: number;
  ariaLabel: string;
  onClick?: (p: EChartClickParams) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const clickRef = useRef(onClick);
  const [width, setWidth] = useState(0);
  const narrow = width > 0 && width < NARROW_PX;
  const cats = xCategories(option);
  const minWidth = narrow && cats > 6 ? cats * PX_PER_CATEGORY : undefined;

  useEffect(() => {
    clickRef.current = onClick;
  }, [onClick]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const instance = echarts.init(el, undefined, { renderer: "svg" });
    chart.current = instance;
    instance.on("click", (p) => {
      const params = p as unknown as EChartClickParams;
      clickRef.current?.({ name: params.name, dataIndex: params.dataIndex, seriesName: params.seriesName });
    });
    const ro = new ResizeObserver(() => {
      instance.resize();
      if (box.current) setWidth(box.current.clientWidth);
    });
    ro.observe(el);
    if (box.current) ro.observe(box.current);
    return () => {
      ro.disconnect();
      instance.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption({ aria: { enabled: true }, ...(narrow ? narrowOption(option) : option) }, { notMerge: true });
  }, [option, narrow]);

  return (
    <div ref={box} className={minWidth ? "overflow-x-auto overscroll-x-contain" : undefined}>
      <div
        ref={ref}
        role="img"
        aria-label={ariaLabel}
        style={{ height: `${height / 16}rem`, width: "100%", minWidth: minWidth ? `${minWidth}px` : undefined, cursor: onClick ? "pointer" : undefined }}
      />
    </div>
  );
}
