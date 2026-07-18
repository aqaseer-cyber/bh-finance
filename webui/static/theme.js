/* v3 ECharts theme — GENERATED from tokens.css at load time (charter:
   one theme file from the tokens; no visual constant may live here). */
"use strict";

(function () {
  const css = getComputedStyle(document.documentElement);
  const v = (name) => css.getPropertyValue(name).trim();

  const theme = {
    color: [v("--s1"), v("--s2"), v("--s3"), v("--s4"), v("--s5"),
            v("--s6")],
    backgroundColor: "transparent",
    textStyle: { fontFamily: v("--font"), color: v("--ink-secondary") },
    axisPointer: {
      lineStyle: { color: v("--baseline") },
      label: { backgroundColor: v("--ink") },
    },
    categoryAxis: {
      axisLine: { lineStyle: { color: v("--baseline") } },
      axisTick: { show: false },
      axisLabel: { color: v("--muted"), fontSize: 12 },
      splitLine: { show: false },
    },
    valueAxis: {
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: v("--muted"), fontSize: 12 },
      splitLine: { lineStyle: { color: v("--gridline") } },
    },
    timeAxis: {
      axisLine: { lineStyle: { color: v("--baseline") } },
      axisLabel: { color: v("--muted"), fontSize: 12 },
      splitLine: { show: false },
    },
    tooltip: {
      backgroundColor: v("--surface-raised"),
      borderColor: v("--gridline"),
      textStyle: { color: v("--ink"), fontSize: 12 },
    },
    grid: { top: 28, right: 16, bottom: 28, left: 56,
            containLabel: false, borderWidth: 0 },
    line: { symbol: "none", lineStyle: { width: 1.6 } },
    bar: { itemStyle: { borderRadius: [2, 2, 0, 0] } },
  };

  if (window.echarts) window.echarts.registerTheme("bhf", theme);
  window.BHF_THEME = theme;
  window.BHF_TOKENS = { v };
})();
