/* v3 Financials screen (charter §2.2) — table-first.

   R1 fidelity, recorded honestly:
   - "Annual model" table: every extracted concept × fiscal year, with
     the per-concept provenance badge (tag audit string) on hover.
   - As-filed IS / BS / CF: the FIX-13d presentation structure (order,
     depth, as-filed labels, totals) with values joined where the
     as-filed concept maps onto an extracted series via the audit tag;
     unmatched lines show the honest dash. The full per-line as-filed
     value join deepens in R2 (four-name validation protocol).
   - Segments: axes as sub-tables, synthesized cells flagged (italic
     tan), tie/discontinuity notes inline.
   - Quarterly toggle: lands in R2 (quarters are derived in the export
     pipeline, not yet serialized) — the control says so. */
"use strict";

(function () {
  const $ = (id) => document.getElementById(id);
  let fin = null, finTicker = null;   // /api/financials cache
  let modelMode = "annual";
  let lastD = null;

  function esc(s) {
    return String(s ?? "").replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  function unitFmt(v, unit) {
    if (unit === "USD/shares") return fmt.moneyRaw(v);
    if (unit === "shares") return fmt.shares(v);
    if (unit === "pure") return fmt.isNil(v) ? fmt.DASH : v.toFixed(4);
    return fmt.money(v);
  }

  const LABELS = {
    revenue: "Revenue", cost_of_revenue: "Cost of revenue",
    gross_profit: "Gross profit", operating_income: "Operating income",
    net_income: "Net income", cfo: "Operating cash flow",
    capex: "Capex", sbc: "Share-based compensation",
    dividends_paid: "Dividends paid", buybacks: "Buybacks",
    diluted_shares: "Diluted shares", eps_diluted: "EPS (diluted)",
    interest_expense: "Interest expense",
    tax_expense: "Tax expense", pretax_income: "Pretax income",
    rnd: "R&D", sga: "SG&A", marketing: "Sales & marketing",
    ga: "G&A", opex_total: "Operating expenses", dna: "D&A",
    cfi: "Investing cash flow", cff: "Financing cash flow",
    total_assets: "Total assets", cash: "Cash & equivalents",
    equity: "Book equity", goodwill: "Goodwill",
    intangibles: "Intangibles", inventory: "Inventory",
    accounts_receivable: "Receivables", accounts_payable: "Payables",
    retained_earnings: "Retained earnings", ppe_net: "PP&E net",
    liabilities_total: "Total liabilities",
    assets_current: "Current assets",
    liabilities_current: "Current liabilities",
    minority_interest: "Minority interest",
    preferred_equity: "Preferred equity",
  };

  function years(f) {
    return (f.fy_ends || []).map((iso) => String(iso).slice(0, 4));
  }

  function fmtConcept(key, v) {
    return key === "diluted_shares" || key === "basic_shares"
      ? fmt.shares(v) : key === "eps_diluted"
        ? fmt.moneyRaw(v) : fmt.money(v);
  }

  function annualModelTable(d) {
    const f = d.fundamentals || {};
    const ys = years(f), series = f.series || {},
          tags = f.tags_used || {};
    const quarterly = modelMode === "quarterly" && fin;
    const cols = quarterly
      ? (fin.quarter_labels || []).concat(["LTM"]) : ys;
    let html = '<table class="tbl"><tr><th>Concept</th>'
      + cols.map((y) => "<th>" + esc(y) + "</th>").join("") + "</tr>";
    for (const [key, arr] of Object.entries(series)) {
      if (!arr || !arr.some((v) => v !== null)) continue;
      const label = LABELS[key] || key;
      const tag = tags[key] || "";
      let cells;
      if (quarterly) {
        const row = (fin.rows || {})[key];
        if (!row) continue;
        cells = (row.q || []).concat([row.ltm]);
        if (!cells.some((v) => v !== null && v !== undefined)) continue;
      } else {
        cells = arr;
      }
      html += "<tr><td>" + esc(label)
        + (tag ? '<span class="badge" title="' + esc(tag)
                 + '">xbrl</span>' : "") + "</td>"
        + cells.map((v) => '<td class="num' + (v < 0 ? " neg" : "")
          + '">' + fmtConcept(key, v) + "</td>").join("")
        + "</tr>";
    }
    return html + "</table>";
  }

  function modelToggle(d) {
    const row = $("fin-model-modes");
    if (!row) return;
    row.innerHTML = [["annual", "Annual"],
                     ["quarterly", "Quarterly + LTM"]].map(([m, l]) =>
      '<button class="' + (m === modelMode ? "active" : "")
      + '" data-m="' + m + '"' + (m === "quarterly" && !fin
        ? " disabled" : "") + ">" + l + "</button>").join("");
    row.onclick = (e) => {
      if (!e.target.dataset.m || e.target.disabled) return;
      modelMode = e.target.dataset.m;
      modelToggle(d);
      $("fin-model").innerHTML = annualModelTable(d);
    };
  }

  function tagToConcept(f) {
    /* reverse the audit strings: first tag token -> our concept key */
    const out = {};
    for (const [concept, audit] of Object.entries(f.tags_used || {})) {
      const first = String(audit).split(/[;(]/)[0].trim();
      if (first) out[first] = concept;
    }
    return out;
  }

  function statementTable(d, rows) {
    /* R2 push 2: the FULL as-filed join — every non-abstract line gets
       its values from /api/financials.statement_values (the same
       annual_values_for_concept the export's statement sheets use,
       extension namespaces included). Fallback: the tag-map join. */
    const f = d.fundamentals || {};
    const ys = years(f), series = f.series || {};
    const rev = tagToConcept(f);
    const sv = (fin && fin.statement_values) || {};
    let html = '<table class="tbl"><tr><th>As filed</th>'
      + ys.map((y) => "<th>" + y + "</th>").join("") + "</tr>";
    for (const r of rows) {
      const full = sv[r.concept];
      const concept = rev[r.concept];
      const arr = full ? full.values
        : concept ? series[concept] : null;
      const unit = full ? full.unit : "";
      const pad = "&nbsp;".repeat(Math.max(0, (r.depth || 0)) * 2);
      const cls = r.is_abstract ? "abstract" : r.is_total ? "total" : "";
      html += "<tr><td class=\"" + cls + "\" title=\""
        + esc(r.concept)
        + (full ? " · as filed (companyfacts, latest amendment wins)"
                  + (unit ? " · " + esc(unit) : "")
           : concept ? " → " + esc(f.tags_used[concept] || "")
           : " · no annual facts for this concept") + "\">"
        + pad + esc(r.label || r.concept) + "</td>"
        + ys.map((_, i) => '<td class="num ' + cls
          + ((arr && arr[i] < 0) ? " neg" : "") + '">'
          + (r.is_abstract ? "" : arr
             ? (full ? unitFmt(arr[i], unit) : fmt.money(arr[i]))
             : fmt.DASH)
          + "</td>").join("") + "</tr>";
    }
    return html + "</table>";
  }

  function segmentsBlock(d) {
    const seg = d.segments;
    if (!seg || !(seg.lines || []).length)
      return '<span class="muted">'
        + esc((seg && seg.status) || "no segment data in this run")
        + "</span>";
    const groups = {};
    for (const ln of seg.lines) {
      const key = ln.group + " by " + ln.axis;
      (groups[key] = groups[key] || []).push(ln);
    }
    const fys = new Set();
    for (const ln of seg.lines)
      for (const e of ln.entries || []) {
        const [s, ee] = e;
        const days = (new Date(ee) - new Date(s)) / 86400000;
        if (days >= 330 && days <= 400) fys.add(String(ee).slice(0, 4));
      }
    const ys = [...fys].sort();
    let html = "";
    for (const [title, lines] of Object.entries(groups)) {
      html += '<div class="card-title" style="margin-top:8px">'
        + esc(title) + "</div>";
      html += '<table class="tbl"><tr><th>Member</th>'
        + ys.map((y) => "<th>FY" + y + "</th>").join("") + "</tr>";
      for (const ln of lines) {
        const byYear = {};
        const synth = new Set((ln.synth || []).map(String));
        for (const e of ln.entries || []) {
          const [s, ee, v] = e;
          const days = (new Date(ee) - new Date(s)) / 86400000;
          if (days >= 330 && days <= 400) {
            const y = String(ee).slice(0, 4);
            byYear[y] = { v, synth: [...synth].some(
              (sy) => sy.includes(String(ee).slice(0, 10))
                   || sy.includes(String(s).slice(0, 10))) };
          }
        }
        html += "<tr><td" + (ln.discontinuous
          ? ' title="interior fiscal year missing while peers have it'
            + ' — likely an unrestated recast"' : "") + ">"
          + esc(ln.member) + (ln.discontinuous ? " ⚠" : "") + "</td>"
          + ys.map((y) => {
              const cell = byYear[y];
              return '<td class="num' + (cell && cell.synth
                ? " synth" : "") + '"' + (cell && cell.synth
                ? ' title="synthesized: summed across the crossing axis'
                  + ', not filed directly"' : "") + ">"
                + (cell ? fmt.money(cell.v) : fmt.DASH) + "</td>";
            }).join("") + "</tr>";
      }
      html += "</table>";
    }
    if ((seg.recast_log || []).length)
      html += '<div class="muted" style="margin-top:8px">recasts: '
        + esc(seg.recast_log.slice(0, 3).join(" · ")) + "</div>";
    return html;
  }

  window.renderFinancials = async function (d) {
    lastD = d;
    if (finTicker !== d.ticker) {
      fin = null;
      finTicker = d.ticker;
      modelMode = "annual";
      try {
        fin = (await api.get("/api/financials/" + d.ticker)).data;
      } catch (e) { fin = null; }
      if (lastD !== d) return;   // a newer run superseded this fetch
    }
    modelToggle(d);
    $("fin-model").innerHTML = annualModelTable(d);
    const st = d.statements || {};
    const put = (id, key, fallback) => {
      const rows = st[key];
      $(id).innerHTML = rows && rows.length
        ? statementTable(d, rows)
        : '<span class="muted">' + esc(d.statements_note
            || fallback || "not available in this run") + "</span>";
    };
    put("fin-is", "income", "income statement structure unavailable");
    put("fin-bs", "balance", "balance sheet structure unavailable");
    put("fin-cf", "cashflow", "cash-flow structure unavailable");
    $("fin-seg").innerHTML = segmentsBlock(d);
    const audit = d.audit_report;
    $("fin-audit").innerHTML = audit
      ? esc(audit.checked + " item-years rechecked — " + audit.matched
          + " match, " + (audit.entries || []).length
          + " flagged (full table in the model export)")
        + '<span class="badge paid" title="'
        + esc((audit.sources || []).join(" + ")
          + " · fetched " + (audit.fetched_at || "?")) + '">audit</span>'
      : '<span class="muted">provider recheck off — no keys</span>';
  };
})();
