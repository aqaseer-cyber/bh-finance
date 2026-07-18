/* v3 Overview screen (charter §2.1): profile strip · price chart with
   range + drawdown toggle INSIDE the chart card · verdict strip · KPI
   row · estimates card (FMP, badged) · insider card (EDGAR Form 4).
   Rendering only — every value arrives serialized from /api. */
"use strict";

(function () {
  let priceChart = null, priceSeries = null;
  let state = { range: "5y", mode: "price" };

  const $ = (id) => document.getElementById(id);

  function esc(s) {
    return String(s ?? "").replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  function badge(text, title, paid) {
    return '<span class="badge' + (paid ? " paid" : "") + '" title="'
      + esc(title || "") + '">' + esc(text) + "</span>";
  }

  function profileStrip(d) {
    const p = d.profile || {};
    const [lo52, hi52] = pres.minmax(
      (d.price_closes || []).slice(-252));
    const closes = d.price_closes || [];
    const dayDelta = closes.length >= 2
      ? closes[closes.length - 1] / closes[closes.length - 2] - 1 : null;
    $("ov-profile").innerHTML =
      '<span class="name">' + esc(p.name || d.company) + "</span>"
      + '<span class="muted">' + esc(d.ticker)
      + (p.exchange ? " · " + esc(p.exchange) : "")
      + (d.sic_code ? " · SIC " + esc(d.sic_code) : "") + "</span>"
      + '<span class="num">' + fmt.moneyRaw(d.last_close) + "</span>"
      + '<span class="num ' + (dayDelta > 0 ? "kpi-value pos"
                               : dayDelta < 0 ? "kpi-value neg" : "")
      + '" style="font-size:13px">' + fmt.pct(dayDelta) + " d/d</span>"
      + '<span class="muted num">52w ' + fmt.moneyRaw(lo52) + " – "
      + fmt.moneyRaw(hi52) + "</span>"
      + (p.sources ? badge("profile", p.sources + (p.fetched_at
          ? " · fetched " + p.fetched_at : ""), true) : "");
  }

  function drawPrice(d) {
    const el = $("ov-price");
    if (!priceChart) {
      priceChart = LightweightCharts.createChart(el, {
        layout: { background: { color: "transparent" },
                  textColor: BHF_TOKENS.v("--muted"), fontSize: 12 },
        grid: { vertLines: { visible: false },
                horzLines: { color: BHF_TOKENS.v("--gridline") } },
        timeScale: { borderColor: BHF_TOKENS.v("--baseline") },
        rightPriceScale: { borderColor: BHF_TOKENS.v("--baseline") },
        crosshair: { mode: 0 },
        autoSize: true,
      });
      priceSeries = priceChart.addSeries(LightweightCharts.LineSeries, {
        color: BHF_TOKENS.v("--s1"), lineWidth: 2,
        priceLineVisible: false,
      });
    }
    const dates = d.price_dates || [];
    const src = state.mode === "drawdown" ? (d.drawdown || [])
                                          : (d.price_closes || []);
    const days = { "1y": 252, "3y": 756, "5y": 1260, max: Infinity };
    const keep = Math.min(dates.length, days[state.range] || Infinity);
    const rows = [];
    for (let i = dates.length - keep; i < dates.length; i++) {
      if (i < 0 || src[i] === null || src[i] === undefined) continue;
      rows.push({ time: dates[i],
                  value: state.mode === "drawdown"
                    ? src[i] * 100 : src[i] });
    }
    priceSeries.applyOptions({
      color: state.mode === "drawdown" ? BHF_TOKENS.v("--neg")
                                       : BHF_TOKENS.v("--s1"),
    });
    priceSeries.setData(rows);
    priceChart.timeScale().fitContent();
    $("ov-price-foot").textContent =
      (state.mode === "drawdown"
        ? "drawdown from running peak, % · " : "daily close, "
          + "split-adjusted · ") + (d.price_source || "–");
  }

  function toggles(d) {
    const mk = (items, cur, cb) => items.map(([k, label]) =>
      '<button class="' + (k === cur ? "active" : "") + '" data-k="'
      + k + '">' + label + "</button>").join("");
    const rangeEl = $("ov-range"), modeEl = $("ov-mode");
    rangeEl.innerHTML = mk([["1y", "1Y"], ["3y", "3Y"], ["5y", "5Y"],
                            ["max", "Max"]], state.range);
    modeEl.innerHTML = mk([["price", "Price"],
                           ["drawdown", "Drawdown"]], state.mode);
    rangeEl.onclick = (e) => {
      if (!e.target.dataset.k) return;
      state.range = e.target.dataset.k; toggles(d); drawPrice(d);
    };
    modeEl.onclick = (e) => {
      if (!e.target.dataset.k) return;
      state.mode = e.target.dataset.k; toggles(d); drawPrice(d);
    };
  }

  function verdictStrip(d, ledgerRow) {
    const el = $("ov-verdict");
    if (!ledgerRow) {
      el.innerHTML = '<span class="muted">No verdict on the ledger yet '
        + "— run Intrinsic value (Valuation screen lands in R2; the Tk "
        + "app remains the valuation surface until then).</span>";
      return;
    }
    const mos = ledgerRow.mos;
    el.innerHTML =
      "<b>" + esc(ledgerRow.rating || "–") + "</b>"
      + ' · FV ' + (ledgerRow.fv_avg != null
        ? fmt.moneyRaw(ledgerRow.fv_avg) : fmt.DASH)
      + ' · MoS <span class="' + (mos > 0 ? "kpi-value pos"
        : mos < 0 ? "kpi-value neg" : "")
      + '" style="font-size:13px">' + fmt.pct(mos) + "</span>"
      + ' · <span class="muted">' + esc(ledgerRow.coherence || "")
      + "</span>"
      + badge("ledger", "verdict ledger (SQLite) · age "
              + (ledgerRow.age_days ?? "?") + "d");
  }

  function kpiRow(d) {
    const tiles = [
      ["Revenue (latest FY)", fmt.money(pres.last(
        (d.fundamentals || {}).series?.revenue))],
      ["Op margin", fmt.pctPlain(pres.last(d.operating_margin))],
      ["ROIC", fmt.pctPlain(pres.last(d.roic))],
      ["FCF", fmt.money(pres.last(d.fcf))],
      ["Adj FCF yield", fmt.pctPlain(d.adj_fcf_yield_now)],
      ["Owner's yield*", fmt.pctPlain(d.owners_yield)],
      ["P/E (FY)", fmt.ratio(pres.last(d.pe_fy))],
      ["EV/EBIT (FY)", fmt.ratio(pres.last(d.ev_ebit_fy))],
    ];
    $("ov-kpis").innerHTML = tiles.map(([label, value]) =>
      '<div class="kpi"><span class="kpi-label">' + esc(label)
      + '</span><span class="kpi-value num">' + value
      + "</span></div>").join("");
  }

  function estimatesCard(d) {
    const el = $("ov-est"), panel = d.estimates_panel;
    if (!panel) {
      el.innerHTML = '<span class="muted">unavailable — FMP key not '
        + "configured</span>";
      return;
    }
    const rows = panel.rows || [];
    const rev = (d.fundamentals || {}).series?.revenue || [];
    const fyEnds = (d.fundamentals || {}).fy_ends || [];
    const actualByYear = {};
    fyEnds.forEach((iso, i) => {
      actualByYear[String(iso).slice(0, 4)] = rev[i];
    });
    let html = '<table class="tbl"><tr><th>FY</th><th>Consensus rev'
      + "</th><th>Actual</th><th>Δ</th></tr>";
    for (const r of rows.slice().reverse()) {
      const y = String(r.date || "").slice(0, 4);
      const est = r.revenueAvg ?? r.estimatedRevenueAvg;
      const act = actualByYear[y];
      const delta = act != null && est ? act / est - 1 : null;
      html += "<tr><td>" + esc(y) + '</td><td class="num">'
        + fmt.money(est) + '</td><td class="num">' + fmt.money(act)
        + '</td><td class="num ' + (delta > 0 ? "" : delta < 0
          ? "neg" : "") + '">' + fmt.pct(delta) + "</td></tr>";
    }
    html += "</table>";
    const t = (panel.trends || [])[0];
    if (t) {
      html += '<div class="muted" style="margin-top:8px">Street ('
        + esc(String(t.period || "").slice(0, 7)) + "): "
        + (t.strongBuy || 0) + " strong buy · " + (t.buy || 0)
        + " buy · " + (t.hold || 0) + " hold · " + (t.sell || 0)
        + " sell" + badge("Finnhub", "recommendation trends, free tier"
        + " · fetched " + (panel.fetched_at || "?"), true) + "</div>";
    }
    el.innerHTML = html;
  }

  function insiderCard(d) {
    const el = $("ov-insiders"), panel = d.insiders;
    if (!panel) {
      el.innerHTML = '<span class="muted">unavailable — needs a '
        + "declared SEC User-Agent</span>";
      return;
    }
    const rows = panel.rows || [];
    if (!rows.length) {
      el.innerHTML = '<span class="muted">no open-market Form 4 '
        + "transactions in the last " + panel.window_months
        + " months</span>";
      return;
    }
    let html = '<table class="tbl"><tr><th>Date</th><th>Insider</th>'
      + "<th>Title</th><th>Type</th><th>Price</th><th>Qty</th>"
      + "<th>Value</th></tr>";
    for (const t of rows.slice(0, 12)) {
      const buy = t.shares > 0;
      html += '<tr style="color:' + (buy
        ? "var(--pos)" : "var(--ink)") + '"><td>' + fmt.date(t.date)
        + "</td><td>" + esc(t.name) + "</td><td>" + esc(t.title)
        + "</td><td>" + esc((t.code || "").split(" — ").pop())
        + '</td><td class="num">' + fmt.moneyRaw(t.price)
        + '</td><td class="num">' + fmt.count(t.shares)
        + '</td><td class="num">' + fmt.money(t.value) + "</td></tr>";
    }
    html += "</table>";
    el.innerHTML = html;
    $("ov-insiders-foot").textContent = panel.note || "";
  }

  window.renderOverview = function (d, ledgerRow) {
    profileStrip(d);
    toggles(d);
    drawPrice(d);
    verdictStrip(d, ledgerRow);
    kpiRow(d);
    estimatesCard(d);
    insiderCard(d);
  };
})();
