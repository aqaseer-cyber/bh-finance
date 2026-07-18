/* v3 Valuation screen (charter §2.4): anchors readout · case table ·
   football field · sensitivity grid · live DCF sandbox · reverse-DCF
   + coherence gates · verdict block with triggers. One screen owns
   the §4–§5 story. ALL math happens in Python via /api — this file
   renders and posts. */
"use strict";

(function () {
  const $ = (id) => document.getElementById(id);
  let ffChart = null;
  let lastData = null;

  function esc(s) {
    return String(s ?? "").replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  const CASE_FIELDS = {
    dcf: [["g0", "Stage-1 g₀ %"], ["g_term", "Terminal g %"]],
    ri: [["roe", "ROE %"], ["g0", "g₀ %"], ["g_term", "Terminal g %"]],
    affo: [["affo_ps", "AFFO/share $"], ["target_yield", "Yield %"]],
    manual: [["fv_ps", "FV/share $"]],
  };
  const PCT_FIELDS = new Set(["g0", "g_term", "roe", "target_yield"]);

  function caseGrid(method, seeds) {
    const fields = CASE_FIELDS[method] || CASE_FIELDS.dcf;
    let html = "<tr><th></th>" + fields.map(([, label]) =>
      "<th>" + esc(label) + "</th>").join("") + "</tr>";
    for (const name of ["Bear", "Base", "Bull"]) {
      html += "<tr><td>" + name + "</td>" + fields.map(([f]) => {
        const seed = seeds && seeds[name] !== undefined && f === "g0"
          ? (seeds[name] * 100).toFixed(1)
          : f === "g_term" ? "2.0" : "";
        return '<td><input class="num" size="6" data-case="' + name
          + '" data-field="' + f + '" value="' + seed + '"></td>';
      }).join("") + "</tr>";
    }
    $("val-cases").innerHTML = html;
  }

  async function loadAnchors(ticker) {
    try {
      const body = await api.get("/api/anchors/" + ticker);
      const a = body.data;
      $("val-anchors").textContent =
        a.readout || "no growth anchors available";
      const method = a.suggested_method || "dcf";
      $("val-method").value = method;
      const wacc = a.wacc_build && a.wacc_build.wacc;
      if (wacc) $("val-wacc").value = (wacc * 100).toFixed(2);
      caseGrid(method, (a.anchors || {}).seeds);
    } catch (e) {
      $("val-anchors").textContent = "anchors unavailable: " + e.message;
      caseGrid("dcf", null);
    }
  }

  function footballField(res) {
    const el = $("val-field");
    if (!ffChart) ffChart = echarts.init(el, "bhf");
    const cases = (res.cases || []).filter((c) => c.fv_ps != null);
    ffChart.setOption({
      tooltip: { trigger: "axis" },
      grid: { left: 64, right: 24, top: 8, bottom: 24 },
      xAxis: { type: "value",
               axisLabel: { formatter: (v) => "$" + v.toFixed(0) } },
      yAxis: { type: "category",
               data: cases.map((c) => c.name) },
      series: [{
        type: "bar", data: cases.map((c) => c.fv_ps),
        label: { show: true, position: "right",
                 formatter: (p) => fmt.moneyRaw(p.value) },
        markLine: res.price != null ? {
          symbol: "none",
          label: { formatter: "P₀ " + fmt.moneyRaw(res.price) },
          data: [{ xAxis: res.price }],
        } : undefined,
      }],
    }, true);
    ffChart.resize();
  }

  function caseTable(res, verdict) {
    let html = '<table class="tbl"><tr><th>Case</th><th>FV/share</th>'
      + "<th>MoS</th></tr>";
    for (const c of res.cases || []) {
      html += "<tr><td>" + esc(c.name) + '</td><td class="num">'
        + fmt.moneyRaw(c.fv_ps) + '</td><td class="num'
        + (c.mos < 0 ? " neg" : "") + '">' + fmt.pct(c.mos)
        + "</td></tr>";
    }
    if (verdict && verdict.fv_avg != null) {
      html += '<tr><td class="total">FV average</td>'
        + '<td class="num total">' + fmt.moneyRaw(verdict.fv_avg)
        + '</td><td class="num total' + (verdict.mos < 0 ? " neg" : "")
        + '">' + fmt.pct(verdict.mos) + "</td></tr>";
    }
    $("val-cases-out").innerHTML = html + "</table>";
  }

  function sensitivity(sens) {
    if (!sens || !sens.cells) {
      $("val-sens").innerHTML =
        '<span class="muted">no sensitivity for this method</span>';
      return;
    }
    let html = "<div class='muted'>" + esc(sens.title) + "</div>"
      + '<table class="tbl"><tr><th>' + esc(sens.row_hdr) + "</th>"
      + sens.col_labels.map((c) => "<th>" + esc(c) + "</th>").join("")
      + "</tr>";
    sens.cells.forEach((row, i) => {
      html += "<tr><td>" + esc(sens.row_labels[i]) + "</td>"
        + row.map((v, j) => '<td class="num'
          + (sens.center && sens.center[0] === i
             && sens.center[1] === j ? " total" : "") + '">'
          + (v == null ? fmt.DASH : fmt.moneyRaw(v))
          + "</td>").join("") + "</tr>";
    });
    $("val-sens").innerHTML = html + "</table>";
  }

  function extras(res) {
    const bits = [];
    if (res.implied_g != null)
      bits.push("reverse DCF: market implies g ≈ "
        + fmt.pct(res.implied_g));
    if (res.implied_return_now != null)
      bits.push("implied return at P₀: "
        + fmt.pct(res.implied_return_now) + "/yr");
    if (res.hurdle_price != null)
      bits.push(fmt.pctPlain(res.hurdle_rate, 0)
        + " hurdle buys at ≤ " + fmt.moneyRaw(res.hurdle_price)
        + " (ASSUMPTION)");
    if (res.irr_ladder && res.irr_ladder.length)
      bits.push("ladder: " + res.irr_ladder.filter((_, i) => i % 2 === 0)
        .map((p) => fmt.moneyRaw(p[0], 0) + "→"
          + (p[1] == null ? "n/a" : fmt.pct(p[1], 0))).join("  "));
    if (res.exit_check && res.exit_check.fv_today != null)
      bits.push("5y exit cross-check: median EV/EBIT "
        + res.exit_check.multiple.toFixed(1) + "× ⇒ "
        + fmt.moneyRaw(res.exit_check.fv_today)
        + "/sh today (companion, not in FV_avg)");
    if (res.rate_build) bits.push("rate build: " + esc(res.rate_build));
    $("val-extras").innerHTML =
      bits.map((b) => "<div>" + b + "</div>").join("");
  }

  function verdictBlock(verdict, triggers) {
    if (!verdict) { $("val-verdict").innerHTML = ""; return; }
    let html = "<div><b>" + esc(verdict.coherence || "") + "</b></div>";
    if (verdict.stressed_mos != null)
      html += "<div>stressed MoS " + fmt.pct(verdict.stressed_mos)
        + "</div>";
    for (const n of verdict.notes || [])
      html += '<div class="muted">' + esc(n) + "</div>";
    if ((triggers || []).length)
      html += "<div style='margin-top:8px'><b>open triggers</b>"
        + triggers.map((t) => '<div class="muted">· '
          + esc(t.trigger_text || "") + "</div>").join("") + "</div>";
    $("val-verdict").innerHTML = html;
  }

  async function compute() {
    if (!lastData) return;
    const method = $("val-method").value;
    const cases = {};
    document.querySelectorAll("#val-cases input").forEach((inp) => {
      const name = inp.dataset.case, f = inp.dataset.field;
      const raw = parseFloat(inp.value);
      if (Number.isNaN(raw)) return;
      (cases[name] = cases[name] || {})[f] =
        PCT_FIELDS.has(f) ? raw / 100 : raw;
    });
    const body = {
      ticker: lastData.ticker, method, cases,
      ex_sbc: $("val-exsbc").checked,
      rating: $("val-rating").value || "",
    };
    const wacc = parseFloat($("val-wacc").value);
    if (!Number.isNaN(wacc)) body.discount_rate = wacc / 100;
    $("val-status").textContent = "computing…";
    try {
      const out = (await api.post("/api/valuation", body)).data;
      $("val-status").textContent = "";
      caseTable(out.result, out.verdict);
      footballField(out.result);
      sensitivity(out.sensitivity);
      extras(out.result);
      verdictBlock(out.verdict, out.triggers);
      sandboxSeed(out.result);
    } catch (e) {
      $("val-status").textContent = "FAILED: " + e.message;
    }
  }

  /* ---- sandbox: sliders over /api/sandbox (FIX-15c compute) ---- */
  let sbTimer = null;
  function sandboxSeed(res) {
    if (res.base_value != null)
      $("sb-base").value = (res.base_value / 1e6).toFixed(0);
    if (res.bridge != null)
      $("sb-bridge").value = (res.bridge / 1e6).toFixed(0);
    if (res.shares != null)
      $("sb-shares").value = (res.shares / 1e6).toFixed(1);
    if (res.discount_rate != null)
      $("sb-wacc").value = (res.discount_rate * 100).toFixed(1);
    sandboxGo();
  }

  function sandboxGo() {
    clearTimeout(sbTimer);
    sbTimer = setTimeout(async () => {
      const val = (id) => parseFloat($(id).value);
      $("sb-wacc-l").textContent = val("sb-wacc").toFixed(1) + "%";
      $("sb-g0-l").textContent = val("sb-g0").toFixed(1) + "%";
      $("sb-gt-l").textContent = val("sb-gt").toFixed(1) + "%";
      if ([val("sb-base"), val("sb-wacc"), val("sb-g0"),
           val("sb-gt")].some(Number.isNaN)) return;
      try {
        const out = (await api.post("/api/sandbox", {
          base: val("sb-base") * 1e6, wacc: val("sb-wacc") / 100,
          g0: val("sb-g0") / 100, g_term: val("sb-gt") / 100,
          bridge: (val("sb-bridge") || 0) * 1e6,
          shares: (val("sb-shares") || 0) * 1e6,
          sbc: 0, ex_sbc: false,
          price: lastData ? lastData.last_close : null,
        })).data;
        $("sb-out").innerHTML = out.error
          ? '<span class="neg">' + esc(out.error) + "</span>"
          : "FV " + fmt.moneyRaw(out.fv_ps)
            + " · MoS " + fmt.pct(out.mos)
            + " · TV share " + fmt.pctPlain(out.tv_share, 0)
            + " · implied g " + fmt.pct(out.implied_g)
            + " · return @P₀ " + fmt.pct(out.implied_return);
      } catch (e) { /* transient while typing */ }
    }, 150);
  }

  window.renderValuation = function (d) {
    lastData = d;
    loadAnchors(d.ticker);
    $("val-method").onchange = () =>
      caseGrid($("val-method").value, null);
    $("val-go").onclick = compute;
    ["sb-wacc", "sb-g0", "sb-gt", "sb-base", "sb-bridge",
     "sb-shares"].forEach((id) => { $(id).oninput = sandboxGo; });
  };
})();
