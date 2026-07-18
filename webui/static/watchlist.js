/* v3 Watchlist screen (charter §2.5): the ledger table — sortable,
   MoS-colored, stale rows flagged, history drawer, re-run action.
   Data: /api/ledger + /api/ledger/{ticker}. */
"use strict";

(function () {
  const $ = (id) => document.getElementById(id);
  let rows = [], sortKey = "ticker", sortAsc = true, openRow = null;

  function esc(s) {
    return String(s ?? "").replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  const COLS = [
    ["ticker", "Ticker"], ["rating", "Rating"], ["fv_avg", "FV avg"],
    ["mos", "MoS"], ["stressed_mos", "Stressed"],
    ["coherence", "Gate"], ["age_days", "Age"],
  ];

  function render() {
    const sorted = rows.slice().sort((a, b) => {
      const x = a[sortKey], y = b[sortKey];
      const cmp = x == null ? 1 : y == null ? -1
        : typeof x === "string" ? x.localeCompare(y) : x - y;
      return sortAsc ? cmp : -cmp;
    });
    let html = '<table class="tbl"><tr>' + COLS.map(([k, label]) =>
      '<th data-k="' + k + '" style="cursor:pointer">' + label
      + (k === sortKey ? (sortAsc ? " ↑" : " ↓") : "") + "</th>")
      .join("") + "<th></th></tr>";
    for (const r of sorted) {
      html += '<tr data-t="' + esc(r.ticker) + '">'
        + "<td><b>" + esc(r.ticker) + "</b></td>"
        + "<td" + (r.stale ? ' style="color:var(--neg)" title="price '
          + 'stale (> ~5 trading days)"' : "") + ">"
        + esc(r.rating || "–") + "</td>"
        + '<td class="num">' + (r.fv_avg != null
          ? fmt.moneyRaw(r.fv_avg) : fmt.DASH) + "</td>"
        + '<td class="num" style="color:' + (r.mos > 0 ? "var(--pos)"
          : r.mos < 0 ? "var(--neg)" : "var(--ink)") + '">'
        + fmt.pct(r.mos) + "</td>"
        + '<td class="num">' + fmt.pct(r.stressed_mos) + "</td>"
        + "<td>" + esc(r.coherence || "") + "</td>"
        + '<td class="num">' + (r.age_days ?? "?") + "d</td>"
        + '<td><button class="rerun" data-t="' + esc(r.ticker)
        + '">re-run</button></td></tr>';
      if (openRow === r.ticker)
        html += '<tr><td colspan="8"><div id="wl-history"'
          + ' class="muted">loading history…</div></td></tr>';
    }
    $("wl-table").innerHTML = html + "</table>";

    $("wl-table").querySelectorAll("th[data-k]").forEach((th) => {
      th.onclick = () => {
        const k = th.dataset.k;
        if (k === sortKey) sortAsc = !sortAsc;
        else { sortKey = k; sortAsc = true; }
        render();
      };
    });
    $("wl-table").querySelectorAll("button.rerun").forEach((b) => {
      b.onclick = (e) => {
        e.stopPropagation();
        store.ticker = b.dataset.t;
        store.screen = "overview";
        store.run();
      };
    });
    $("wl-table").querySelectorAll("tr[data-t]").forEach((tr) => {
      tr.onclick = async () => {
        const t = tr.dataset.t;
        openRow = openRow === t ? null : t;
        render();
        if (openRow) {
          try {
            const h = (await api.get("/api/ledger/" + t)).data;
            const el = $("wl-history");
            if (el) el.innerHTML = h.length
              ? h.map((row) => esc(row.recorded_at) + " · "
                  + esc(row.rating || "–") + " · FV "
                  + (row.fv_avg != null ? fmt.moneyRaw(row.fv_avg)
                     : fmt.DASH) + " · MoS " + fmt.pct(row.mos)
                  + " · " + esc(row.coherence || "")).join("<br>")
              : "no history";
          } catch (e) { /* drawer is best-effort */ }
        }
      };
    });
  }

  window.renderWatchlist = async function () {
    try {
      rows = (await api.get("/api/ledger")).data || [];
    } catch (e) {
      $("wl-table").innerHTML =
        '<span class="muted">ledger unavailable: ' + esc(e.message)
        + "</span>";
      return;
    }
    if (!rows.length) {
      $("wl-table").innerHTML = '<span class="muted">the ledger is '
        + "empty — every computed verdict logs here automatically"
        + "</span>";
      return;
    }
    render();
  };
})();
