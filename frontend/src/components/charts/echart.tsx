"use client";

import { BarChart, LineChart } from "echarts/charts";
import { AriaComponent, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

echarts.use([BarChart, LineChart, GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, AriaComponent, SVGRenderer]);

export type EChartsOption = echarts.EChartsCoreOption;
export interface EChartClickParams {
  name: string;
  dataIndex: number;
  seriesName?: string;
}

/** Thin React wrapper around ECharts (modular build, SVG renderer). */
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
  const chart = useRef<echarts.ECharts | null>(null);
  const clickRef = useRef(onClick);

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
    const ro = new ResizeObserver(() => instance.resize());
    ro.observe(el);
    return () => {
      ro.disconnect();
      instance.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption({ aria: { enabled: true }, ...option }, { notMerge: true });
  }, [option]);

  return <div ref={ref} role="img" aria-label={ariaLabel} style={{ height, width: "100%", cursor: onClick ? "pointer" : undefined }} />;
}
