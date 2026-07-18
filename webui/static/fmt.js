/* v3 shared formatting (charter §1) — mirrors the Python formatting:
   $mm with thin separators, signed percents, dash for null. The ONLY
   place display formatting lives in JS. No analytics here, ever. */
"use strict";

const fmt = {
  DASH: "–",
  isNil(v) { return v === null || v === undefined || Number.isNaN(v); },

  money(v) {                       // dollars -> $mm, thin separators
    if (fmt.isNil(v)) return fmt.DASH;
    const mm = v / 1e6;
    const s = Math.abs(mm) >= 100
      ? Math.round(mm).toLocaleString("en-US")
      : mm.toLocaleString("en-US", { maximumFractionDigits: 1 });
    return (mm < 0 ? "($" + s.replace("-", "") + "M)" : "$" + s + "M")
      .replace(/,/g, " ");
  },

  moneyRaw(v, digits = 2) {        // per-share / price dollars
    if (fmt.isNil(v)) return fmt.DASH;
    return "$" + v.toLocaleString("en-US",
      { minimumFractionDigits: digits, maximumFractionDigits: digits });
  },

  pct(v, digits = 1) {             // fraction -> signed percent
    if (fmt.isNil(v)) return fmt.DASH;
    const s = (v * 100).toFixed(digits);
    return (v > 0 ? "+" : "") + s + "%";
  },

  pctPlain(v, digits = 1) {        // unsigned percent (margins etc.)
    if (fmt.isNil(v)) return fmt.DASH;
    return (v * 100).toFixed(digits) + "%";
  },

  ratio(v) {
    if (fmt.isNil(v)) return fmt.DASH;
    return v.toFixed(1) + "×";
  },

  shares(v) {
    if (fmt.isNil(v)) return fmt.DASH;
    return (v / 1e6).toLocaleString("en-US",
      { maximumFractionDigits: 1 }) + "M";
  },

  count(v) {
    if (fmt.isNil(v)) return fmt.DASH;
    return v.toLocaleString("en-US");
  },

  date(iso) { return iso ? String(iso).slice(0, 10) : fmt.DASH; },
};

window.fmt = fmt;
