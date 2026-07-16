import * as echarts from "echarts";
import { useEffect, useRef } from "react";
import { useTheme } from "../hooks/use-theme";

interface Timeline {
  labels: string[];
  timestamps: number[];
  base: number[];
  event: number[];
  residual: number[];
  mitigated_residual: number[];
  observed: number[];
  incidents: Array<{ incident_id: string; label: string; index: number }>;
}

export function DecompositionChart({
  timeline,
  cursor,
  service,
  onIncidentOpen,
}: {
  timeline: Timeline;
  cursor: number;
  service: string;
  onIncidentOpen: (incidentId: string) => void;
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
      dataZoom: [
        { type: "inside", start: 0, end: 100 },
        { type: "slider", height: 14, bottom: 2, borderColor: "transparent" },
      ],
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
          markArea: {
            silent: false,
            itemStyle: { color: "rgba(235, 165, 52, 0.08)" },
            data: timeline.incidents.map((incident) => [
              {
                name: incident.label,
                xAxis: Math.max(0, incident.index - 1),
                incidentId: incident.incident_id,
              },
              { xAxis: Math.min(timeline.labels.length - 1, incident.index + 1) },
            ]),
          },
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
    chart.on("click", (params) => {
      const incidentId = (
        params.data as { incidentId?: string } | undefined
      )?.incidentId;
      if (incidentId) onIncidentOpen(incidentId);
    });
    chart.on("datazoom", () => {
      const option = chart.getOption();
      const zoom = (option.dataZoom as Array<{ start?: number; end?: number }> | undefined)?.[0];
      const start = Math.round(((zoom?.start ?? 0) / 100) * (timeline.timestamps.length - 1));
      const end = Math.round(((zoom?.end ?? 100) / 100) * (timeline.timestamps.length - 1));
      void fetch(
        `/api/decomp?service=${encodeURIComponent(service)}&signal=rps&from_ts=${timeline.timestamps[start]}&to_ts=${timeline.timestamps[end]}&max_points=2000`,
      );
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [cursor, onIncidentOpen, service, theme, timeline]);

  return (
    <div
      ref={ref}
      className="h-80 w-full"
      aria-label={`Surge decomposition chart filtered to ${service}`}
    />
  );
}
