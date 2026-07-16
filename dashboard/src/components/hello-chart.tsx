import * as echarts from "echarts";
import { useEffect, useRef } from "react";
import { useTheme } from "../hooks/use-theme";

// Placeholder proving the charting pipeline end to end; the real panels
// replace it with contract-driven data. Colors come from the live brand
// tokens, so the chart follows the theme.
export function HelloChart() {
  const ref = useRef<HTMLDivElement>(null);
  const theme = useTheme();

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const tokens = getComputedStyle(el);
    const chart = echarts.init(el);
    const points = Array.from(
      { length: 96 },
      (_, i) => 100 + 60 * Math.sin(i / 8) + 14 * Math.sin(i / 2.3),
    );
    chart.setOption({
      grid: { left: 8, right: 8, top: 8, bottom: 8 },
      xAxis: { type: "category", show: false, data: points.map((_, i) => i) },
      yAxis: { type: "value", show: false },
      series: [
        {
          type: "line",
          data: points,
          smooth: true,
          showSymbol: false,
          lineStyle: { color: tokens.getPropertyValue("--brand").trim(), width: 2 },
          areaStyle: { color: tokens.getPropertyValue("--accent-soft").trim() },
        },
      ],
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [theme]);

  return <div ref={ref} className="h-40 w-full" aria-hidden="true" />;
}
