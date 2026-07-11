# Master fix bundle — owner handoff (`fix-bundle-11-13-10-12`)

All four fix-series are integrated on this one branch in the bundle's
execution order **FIX-11 → FIX-13 → FIX-10 → FIX-12** (30 commits from
`main` @ `071b780`, per-spec commit sequences and messages preserved, plus
the CI quickjs-best-effort commit and one integration-hardening commit).

## Code-side gates — verified in the implementation environment

- Suite green after **every** commit (final: 200 passed + 4 tkinter-only
  skips that run in CI's Windows/Ubuntu matrix).
- `docs/golden_pre_fix.json` / `golden_post_fix.json` **byte-identical at
  every FIX boundary** — no valuation number moved.
- `assets/forensic_valuation_model_v3.xlsx` untouched.
- `tools/check_pdf_fill.py` on a fixture five-page PDF:

  ```
  page        figure    A4 sheet    fill
     1  12.80x18.10    portrait   100%
     2  12.80x9.05    landscape   100%
     3  12.80x9.05    landscape   100%
     4  12.80x9.05    landscape   100%
     5  12.80x9.05    landscape   100%
  worst fill: 100% (threshold 85%)
  ```

- Bundle integration resolutions honored: `TTL_FILING_INSTANCE` defined
  once (13d), FIX-10 on the 13-fixed parser with post-normalization
  labels, one set of number-format constants (13d) applied everywhere at
  12h, both UA mechanisms (13a gate + 11e hint), one accumulated
  `docs/MELI_VALIDATION.md`, FIX-10b's `fetch_segment_instances` signature
  throughout.

## Live gates — OWNER-RUN, in this order, before merging to main

The implementation environment has no route to sec.gov, so these are
recorded as pending protocols. **Each gate must pass before acting on the
next; do not batch.**

1. **FIX-11f — MELI income-statement basis** — `docs/MELI_VALIDATION.md`,
   first section (headline revenue 28,893/20,777, IS tie ≤0.1%, capex
   quarters populated, interest alive, SBC warning-or-override).
2. **FIX-13f — MELI segments & statement sheets** — same file, second
   section (Commerce 12,159 / Fintech 8,618, 0.0% ties, dedupe to one
   Other Countries line, KPI footnote, placeholder-UA message check).
3. **FIX-10g — four-name segment history** — `docs/SEGMENT_VALIDATION.md`
   (MELI / PYPL / AXON / GSL; tie gaps within ±2% or explained; breaks
   judged; wall time & cache growth recorded).
4. **FIX-12i — Windows 150%-scaling checklist** — `docs/UI_VALIDATION.md`
   (the only gate a human at a scaled display can verify: crisp shell,
   icon, resize re-render, watchlist sort/colours, Settings persistence,
   dense verdict page, export formats on MELI/AAPL).

Requirements for the runs: `SEC_EDGAR_USER_AGENT` set (`name email`);
row 11 of the FIX-13 table additionally needs one run with it **unset**.

## After all gates pass

- Merge `fix-bundle-11-13-10-12` → `main` (the branch is a straight line
  on top of `main`; a fast-forward keeps the 30-commit history).
- Flip the repository default branch to `main` (Settings → General).
- Delete the superseded branches: `fix-10-segment-history`,
  `fix-11-basis-coherence`, `fix-12-presentation`,
  `fix-13-segments-statements`, and the long-stale
  `claude/stock-performance-viz-dlb9j5` (verified fully merged; the
  implementation environment's git proxy refuses to delete its own
  designated branch, so this one is yours).
- FIX-14 (growth discipline) ships as a separate spec after the bundle is
  merged and validated, per the bundle header.

## Standing reminders

- The contact email lives in environment variables only; it remains in
  pre-FIX-9 **git history** until you decide on a filter-repo rewrite or
  accept it.
- Restart open terminals/IDEs/the app after changing environment
  variables — running processes never see new values.
