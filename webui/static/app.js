/* v3 app frame — petite-vue store: nav, ticker bar, SSE run status,
   data loading. THIN: every number on screen came from /api; the only
   JS "computation" permitted is presentation (last-of-series, min/max
   of a served series for a range readout). Analytics live in Python. */
"use strict";

const api = {
  token: window.BHF_TOKEN || "",
  headers() { return { Authorization: "Bearer " + api.token }; },
  async get(path) {
    const r = await fetch(path, { headers: api.headers() });
    if (!r.ok) throw new Error(path + " -> " + r.status);
    return r.json();
  },
  async post(path, body) {
    const r = await fetch(path, {
      method: "POST",
      headers: { ...api.headers(), "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (!r.ok) throw new Error(path + " -> " + r.status);
    return r.json();
  },
};

const store = window.PetiteVue.reactive({
  screen: "overview",
  screens: [
    ["overview", "Overview"],
    ["financials", "Financials"],
    ["quality", "Quality"],
    ["valuation", "Valuation"],
    ["watchlist", "Watchlist"],
  ],
  ticker: "",
  running: false,
  status: "enter a ticker and Run",
  data: null,            // /api/data payload .data
  ledgerRow: null,

  nav(s) {
    store.screen = s;
    store.render();
  },

  async run() {
    const t = (store.ticker || "").trim().toUpperCase();
    if (!t || store.running) return;
    store.running = true;
    store.status = "running " + t + "…";
    try {
      const resp = await fetch("/api/run/" + t + "?token=" + api.token,
                               { method: "POST" });
      const reader = resp.body.getReader();
      const dec = new TextDecoder();
      let buf = "", ok = false;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const chunk = buf.slice(0, idx); buf = buf.slice(idx + 2);
          const ev = (chunk.match(/^event: (.+)$/m) || [])[1];
          const dat = (chunk.match(/^data: (.+)$/m) || [])[1];
          if (ev === "progress" && dat)
            store.status = JSON.parse(dat).message;
          if (ev === "error" && dat)
            store.status = "FAILED: " + JSON.parse(dat).message;
          if (ev === "done") ok = true;
        }
      }
      if (ok) {
        store.status = t + " — loading…";
        await store.load(t);
        store.status = t + " — done.";
      }
    } catch (e) {
      store.status = "FAILED: " + e.message;
    } finally {
      store.running = false;
    }
  },

  async load(t) {
    const body = await api.get("/api/data/" + t);
    store.data = body.data;
    try {
      const led = await api.get("/api/ledger");
      store.ledgerRow =
        (led.data || []).find((r) => r.ticker === t) || null;
    } catch (e) { store.ledgerRow = null; }
    store.render();
  },

  render() {
    // defer one frame so the v-show switch has applied — charts must
    // measure a VISIBLE container or they fall back to a tiny canvas
    requestAnimationFrame(() => {
      if (store.screen === "watchlist" && window.renderWatchlist) {
        window.renderWatchlist();
        return;
      }
      if (!store.data) return;
      if (store.screen === "overview" && window.renderOverview)
        window.renderOverview(store.data, store.ledgerRow);
      if (store.screen === "financials" && window.renderFinancials)
        window.renderFinancials(store.data);
      if (store.screen === "quality" && window.renderQuality)
        window.renderQuality(store.data);
      if (store.screen === "valuation" && window.renderValuation)
        window.renderValuation(store.data);
    });
  },
});

/* series helpers — presentation only */
const pres = {
  last(arr) {
    if (!arr) return null;
    for (let i = arr.length - 1; i >= 0; i--)
      if (arr[i] !== null && arr[i] !== undefined) return arr[i];
    return null;
  },
  minmax(arr) {
    let lo = null, hi = null;
    for (const v of arr || []) {
      if (v === null || v === undefined) continue;
      if (lo === null || v < lo) lo = v;
      if (hi === null || v > hi) hi = v;
    }
    return [lo, hi];
  },
};

window.api = api;
window.store = store;
window.pres = pres;

window.addEventListener("DOMContentLoaded", () => {
  window.PetiteVue.createApp({ store }).mount("#app");
});
