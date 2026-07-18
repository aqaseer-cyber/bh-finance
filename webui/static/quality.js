/* v3 Quality screen (charter §2.3): the merged Health + Unit-economics
   content as cards on ONE scrolling grid — each chart appears exactly
   once in the app. The revenue card carries MODES (the old standalone
   "Revenue growth" / "Revenue architecture" panels died on the kill
   list). Rendering only: every series arrives from /api. */
"use strict";

(function () {
  const charts = {};
  let revMode = "revenue";

  function chart(id) {
    const el = document.getElementById(id);
    if (!el) return null;
    if (!charts[id]) charts[id] = echarts.init(el, "bhf");
    else if (charts[id].getWidth() < el.clientWidth - 4)
      charts[id].resize();   // was initialized while hidden — recover
    return charts[id];
  }

  window.addEventListener("resize", () => {
    for (const c of Object.values(charts)) c.resize();
  });

  function years(d) {
    return (d.fy_labels || []).map((l) => String(l).replace("FY", ""));
  }

  function line(name, data, opts) {
    return Object.assign({ name, type: "line", data,
                           connectNulls: false }, opts || {});
  }

  function bar(name, data, opts) {
    return Object.assign({ name, type: "bar", data }, opts || {});
  }

  function draw(id, series, opts) {
    const c = chart(id);
    if (!c) return;
    c.setOption(Object.assign({
      tooltip: { trigger: "axis" },
      legend: { top: 0, textStyle: { fontSize: 12 } },
      xAxis: { type: "category", data: opts.x },
      yAxis: { type: "value",
               axisLabel: { formatter: opts.yfmt || undefined } },
      series,
    }, opts.extra || {}), true);
    c.resize();
  }

  const pctAxis = (v) => (v * 100).toFixed(0) + "%";
  const mmAxis = (v) => "$" + (v / 1e9).toFixed(0) + "B";

  function revenueCard(d, x) {
    const modes = {
      revenue: () => draw("q-revenue",
        [bar("Revenue", d.fundamentals?.series?.revenue || [])],
        { x, yfmt: mmAxis }),
      growth: () => draw("q-revenue",
        [line("YoY growth", d.revenue_yoy || [])],
        { x, yfmt: pctAxis }),
      margins: () => draw("q-revenue",
        [line("Gross", d.gross_margin || []),
         line("Operating", d.operating_margin || []),
         line("Net", d.net_margin || [])],
        { x, yfmt: pctAxis }),
    };
    const row = document.getElementById("q-rev-modes");
    row.innerHTML = ["revenue", "growth", "margins"].map((m) =>
      '<button class="' + (m === revMode ? "active" : "")
      + '" data-m="' + m + '">' + m + "</button>").join("");
    row.onclick = (e) => {
      if (!e.target.dataset.m) return;
      revMode = e.target.dataset.m;
      revenueCard(d, x);
    };
    (modes[revMode] || modes.revenue)();
  }

  window.renderQuality = function (d) {
    const x = years(d);
    revenueCard(d, x);
    draw("q-piotroski",
         [bar("Piotroski score (of 9)", d.piotroski_score || [])],
         { x, extra: { yAxis: { type: "value", max: 9 } } });
    draw("q-accruals",
         [line("Accruals ratio", d.accruals_ratio || []),
          line("Sloan (full)", d.sloan_full || [])],
         { x, yfmt: pctAxis });
    draw("q-altman", [line("Altman Z", d.altman_z || [])], { x });
    draw("q-sbc",
         [bar("SBC % revenue", d.sbc_pct_revenue || []),
          line("FCF", d.fcf || [], { yAxisIndex: 1 }),
          line("FCF ex-SBC", d.fcf_ex_sbc || [], { yAxisIndex: 1 })],
         { x, extra: { yAxis: [
             { type: "value", axisLabel: { formatter: pctAxis } },
             { type: "value", axisLabel: { formatter: mmAxis } }] } });
    draw("q-rnd", [line("R&D % revenue", d.rnd_pct_revenue || [])],
         { x, yfmt: pctAxis });
    draw("q-ccc",
         [line("CCC (days)", d.ccc || []), line("DSO", d.dso || []),
          line("DSI", d.dsi || []), line("DPO", d.dpo || [])], { x });
    draw("q-returns",
         [line("ROIC", d.roic || []), line("ROE", d.roe || [])],
         { x, yfmt: pctAxis });
    draw("q-incremental",
         [line("Operating margin", d.operating_margin || []),
          line("Incremental op margin",
               d.incremental_op_margin || [])],
         { x, yfmt: pctAxis });
    document.getElementById("q-notes").innerHTML =
      (d.health_notes || []).map((n) =>
        "<div>" + String(n).replace(/[&<>]/g, (c) =>
          ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]))
        + "</div>").join("");
  };
})();
