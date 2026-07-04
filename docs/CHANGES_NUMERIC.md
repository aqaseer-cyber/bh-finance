# Numeric changes — golden snapshot pre vs post fixes

Comparison of `docs/golden_pre_fix.json` (before FIX-1) and
`docs/golden_post_fix.json` (after FIX-9), from the deterministic offline
TESTCO fixture (`tools/golden_snapshot.py`). Every changed number is
attributed to its causing FIX; nothing is unattributed.

| Field | Pre | Post | Cause |
|---|---|---|---|
| `implied_g` | 0.07646790890 | 0.08433540373 | **FIX-2** — reverse-DCF basis moved from the Track-A as-reported FCFF base to the **Track-B ex-SBC base** over market EV, mirroring `Control!B58`. The ex-SBC base is smaller (base − latest SBC), so `FCFF₀/EV` shrinks and the implied g rises. |

## Fields that did **not** change (and why)

- **`market_ev`, `net_debt`, and every case `fv_ps` / `mos` / `tv_share`, and
  the whole `verdict` block** are unchanged. TESTCO has no minority interest,
  preferred equity, or non-operating investments, so the FIX-2 equity **bridge**
  (`net debt + MI + pref − non-op`) equals net debt — identical to the old
  math. The bridge change is exercised numerically instead by
  `tests/test_bridge_parity.py`, which builds a fixture *with* MI/preferred/
  non-op and asserts the `Control!B57/B58/FCFF_DCF!B31` arithmetic to 1e-9.
- **FIX-1** (invested-capital fallback) affects **ROIC**, which is a
  unit-economics metric not present in this valuation snapshot.
- **FIX-3** (fixed beta window) only changes **WACC on live runs**; this
  offline snapshot passes an explicit `discount_rate`, so WACC is not computed
  here.
- **FIX-4/6/7/8/9** are labeling, ledger, config-loading, docs, and hygiene —
  no effect on these computed values.
