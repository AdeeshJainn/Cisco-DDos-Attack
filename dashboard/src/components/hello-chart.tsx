import * as echarts from "echarts";
import { useEffect, useRef } from "react";
import { useTheme } from "../hooks/use-theme";

interface Timeline {
  labels: string[];
  base: number[];
  event: number[];
  residual: number[];
  mitigated_residual: number[];
  observed: number[];
}

export function DecompositionChart({
  timeline,
  cursor,
}: {
  timeline: Timeline;
  cursor: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const theme = useTheme();

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const tokens = getComputedStyle(el);
    const chart = echarts.init(el);
    const visible = (values: number[]) =>
      values.map((value, index) => (index <= cursor ? value : null));
    chart.setOption({
      animationDuration: 700,
      backgroundColor: "transparent",
      grid: { left: 44, right: 16, top: 30, bottom: 34 },
      tooltip: { trigger: "axis" },
      legend: {
        top: 0,
        right: 0,
        textStyle: { color: tokens.getPropertyValue("--muted").trim() },
      },
      xAxis: {
        type: "category",
        data: timeline.labels,
        axisLine: { lineStyle: { color: tokens.getPropertyValue("--line").trim() } },
        axisLabel: {
          color: tokens.getPropertyValue("--muted").trim(),
          interval: 5,
        },
      },
      yAxis: {
        type: "value",
        name: "relative load",
        nameTextStyle: { color: tokens.getPropertyValue("--muted").trim() },
        axisLabel: { color: tokens.getPropertyValue("--muted").trim() },
        splitLine: { lineStyle: { color: tokens.getPropertyValue("--line").trim() } },
      },
      series: [
        {
          name: "base",
          type: "line",
          stack: "expected",
          data: visible(timeline.base),
          smooth: true,
          showSymbol: false,
          lineStyle: {
            color: tokens.getPropertyValue("--decomp-base").trim(),
            width: 1,
          },
          areaStyle: { color: tokens.getPropertyValue("--line").trim() },
        },
        {
          name: "event",
          type: "line",
          stack: "expected",
          data: visible(timeline.event),
          smooth: true,
          showSymbol: false,
          lineStyle: {
            color: tokens.getPropertyValue("--decomp-event").trim(),
            width: 2,
          },
          areaStyle: { color: tokens.getPropertyValue("--accent-soft").trim() },
        },
        {
          name: "residual",
          type: "line",
          data: visible(timeline.residual),
          smooth: true,
          showSymbol: false,
          lineStyle: {
            color: tokens.getPropertyValue("--decomp-residual").trim(),
            width: 2,
            type: "dashed",
          },
        },
        {
          name: "after action",
          type: "line",
          stack: "expected",
          data: visible(timeline.mitigated_residual),
          smooth: true,
          showSymbol: false,
          lineStyle: {
            color: tokens.getPropertyValue("--success").trim(),
            width: 2,
          },
          areaStyle: { opacity: 0.12 },
        },
        {
          name: "observed",
          type: "line",
          data: visible(timeline.observed),
          smooth: true,
          showSymbol: false,
          lineStyle: {
            color: tokens.getPropertyValue("--ink").trim(),
            width: 2,
            type: "dashed",
          },
        },
      ],
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [cursor, theme, timeline]);

  return <div ref={ref} className="h-72 w-full" aria-label="Surge decomposition chart" />;
}
