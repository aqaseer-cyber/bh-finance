"""Command-line entry point.

  python -m forensic_viz                     -> GUI
  python -m forensic_viz AAPL                -> AAPL_10y_report_<date>.pdf (A4)
  python -m forensic_viz AAPL --years 5      -> 5-year window
  python -m forensic_viz AAPL --html         -> interactive HTML report
  python -m forensic_viz AAPL --png --csv    -> per-page PNGs + CSVs

  Intrinsic value (Bear/Base/Bull). WACC auto-builds; for DCF, omitted cases
  pre-fill from analyst consensus (Bear <- low, Base <- avg, Bull <- high,
  terminal g 2.0%):
  python -m forensic_viz AAPL --value dcf --rating Buy
  python -m forensic_viz AAPL --value dcf --bear 0.02,0.02 --base 0.05,0.025 --bull 0.09,0.03
    case syntax per method:
      dcf    g0,g_term      ri  roe,g0,g_term
      affo   affo_per_share,target_yield      manual  fv_per_share
"""
from __future__ import annotations

import argparse
import sys

from . import config
from .cache import Cache
from .edgar import EdgarError


def _report_error(message: str) -> None:
    """Errors must surface even from a --windowed frozen exe (stderr is None)."""
    if sys.stderr is not None:
        print(f"error: {message}", file=sys.stderr)
    if getattr(sys, "frozen", False) and sys.stderr is None:
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("Forensic Stock Viz", message)
            root.destroy()
        except Exception:
            pass


def _parse_case(method: str, raw: str):
    import math

    from .valuation import CaseInputs, ValuationError
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        raise ValuationError(f"case '{raw}' must be comma-separated numbers")
    if not all(math.isfinite(n) for n in nums):
        raise ValuationError(f"case '{raw}' must be finite numbers")
    if method == "dcf":
        if len(nums) != 2:
            raise ValuationError("dcf case needs g0,g_term (e.g. 0.05,0.025)")
        return CaseInputs(g0=nums[0], g_term=nums[1])
    if method == "ri":
        if len(nums) != 3:
            raise ValuationError("ri case needs roe,g0,g_term (e.g. 0.15,0.05,0.03)")
        return CaseInputs(roe=nums[0], g0=nums[1], g_term=nums[2])
    if method == "affo":
        if len(nums) != 2:
            raise ValuationError("affo case needs affo_per_share,target_yield")
        return CaseInputs(affo_ps=nums[0], target_yield=nums[1])
    if len(nums) != 1:
        raise ValuationError("manual case needs a single fv_per_share")
    return CaseInputs(fv_ps=nums[0])


def _build_valuation_result(data, args):
    from .valuation import (
        CASE_NAMES, ValuationError, ValuationInputs, build_valuation,
    )
    method = args.value.lower()
    raws = {"Bear": args.bear, "Base": args.base, "Bull": args.bull}
    cases = {}
    est = data.analyst_estimates or {}
    est_map = {"Bear": est.get("g_low"), "Base": est.get("g_avg"),
               "Bull": est.get("g_high")}
    for name in CASE_NAMES:
        if raws[name]:
            cases[name] = _parse_case(method, raws[name])
        elif method == "dcf" and est_map[name] is not None:
            from .valuation import CaseInputs
            cases[name] = CaseInputs(g0=est_map[name], g_term=0.02)
            print(f"  {name}: g0 {est_map[name] * 100:.1f}% from analyst consensus "
                  f"({est.get('source', '')}), terminal g 2.0% house default")
        else:
            raise ValuationError(
                f"provide --{name.lower()} (no analyst estimate available "
                "to pre-fill it)")
    inputs = ValuationInputs(
        method=method, cases=cases,
        discount_rate=args.wacc, base_value=args.base_value, ex_sbc=args.ex_sbc)
    return build_valuation(data, inputs)


def main(argv=None) -> int:
    from .metrics import TRACKS

    parser = argparse.ArgumentParser(
        prog="forensic-viz",
        description="Five-phase forensic stock report from SEC EDGAR XBRL + daily prices.",
    )
    parser.add_argument("ticker", nargs="?", help="US-listed ticker, e.g. AAPL")
    parser.add_argument("-o", "--out", help="output path (.pdf, or base name with --png)")
    parser.add_argument("--years", type=int, default=config.DISPLAY_YEARS,
                        choices=range(1, config.DISPLAY_YEARS + 1), metavar="N",
                        help=f"fiscal years to display, 1–{config.DISPLAY_YEARS} (default 10)")
    parser.add_argument("--png", action="store_true",
                        help="write per-page PNGs instead of the A4 PDF")
    parser.add_argument("--html", nargs="?", const="", metavar="PATH",
                        help="also write the interactive HTML report")
    parser.add_argument("--csv", action="store_true",
                        help="also write fundamentals/prices (and valuation) CSVs")
    parser.add_argument("--gui", action="store_true", help="launch the desktop app")
    parser.add_argument("--no-cache", action="store_true", help="bypass the local cache")
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--track", choices=list(TRACKS), default="auto",
                        help="logic track override (master Phase 1); auto = from SIC")
    parser.add_argument("--adjusted-ni", type=float,
                        help="fluff filter (§3.1): latest-FY non-GAAP net income in $")
    parser.add_argument("--thesis",
                        help="investment thesis (§2.4), printed on the unit-economics page")
    parser.add_argument("--terminal-risk",
                        help="terminal risk (§2.3, cite Item 1A); anchors the Phase-5 rating")
    parser.add_argument("--non-op-investments", type=float, metavar="DOLLARS",
                        help="non-operating investments for the equity bridge "
                             "(Phase1_Anchor!B19, analyst input; $ not $mm)")

    val = parser.add_argument_group("intrinsic value (Bear/Base/Bull)")
    val.add_argument("--value", choices=["dcf", "ri", "affo", "manual"],
                     help="run the intrinsic-value calculator with this method")
    val.add_argument("--wacc", type=float,
                     help="discount rate override (fraction); omitted = auto-build")
    val.add_argument("--base-value", type=float,
                     help="override base: FCFF $ (dcf) or BV0 $ (ri)")
    val.add_argument("--ex-sbc", action="store_true",
                     help="dcf base on ex-SBC FCF (house §2b, Track B)")
    val.add_argument("--bear", help="Bear case (dcf: pre-fills from analyst LOW estimate)")
    val.add_argument("--base", help="Base case (dcf: pre-fills from analyst AVERAGE estimate)")
    val.add_argument("--bull", help="Bull case (dcf: pre-fills from analyst HIGH estimate)")
    val.add_argument("--rating", choices=["Strong Buy", "Buy", "Hold", "Sell"],
                     help="institutional rating (§5.3, judgment) — coherence-checked only")
    val.add_argument("--optionality",
                     help="§4.D named optionality carrying a rating above a deeply negative MoS")
    parser.add_argument("--xlsx", nargs="?", const="", metavar="PATH",
                        help="export a filled copy of forensic_valuation_model_v3.xlsx")
    parser.add_argument("--ledger", action="store_true",
                        help="print the verdict ledger (§5.7) and exit")
    parser.add_argument("--ledger-history", metavar="TICKER",
                        help="print the append-only verdict history for a ticker")
    parser.add_argument("--ledger-import", metavar="JSON",
                        help="import a verdict_ledger_seed.json-style file")
    parser.add_argument("--compare", metavar="TICKERS",
                        help="comma-separated tickers (2–4): build the "
                             "side-by-side interactive comparison and exit")
    args = parser.parse_args(argv)

    if args.ledger_history:
        from .ledger import Ledger
        for r in Ledger().history(args.ledger_history):
            mos = f"{r['mos'] * 100:+.1f}%" if r["mos"] is not None else "–"
            fv = f"${r['fv_avg']:,.2f}" if r["fv_avg"] is not None else "–"
            print(f"  {r['recorded_at']}  {r['rating'] or '–':<11} FV {fv:<10} "
                  f"MoS {mos:<8} {r['coherence'] or ''}")
        return 0

    if args.ledger or args.ledger_import:
        from .ledger import Ledger
        led = Ledger()
        if args.ledger_import:
            n = led.import_seed(args.ledger_import)
            print(f"imported {n} ledger rows from {args.ledger_import} "
                  "[Likely] — verify vs original workbooks")
        for r in led.list_verdicts():
            mos = f"{r['mos'] * 100:+.1f}%" if r["mos"] is not None else "–"
            fv = f"${r['fv_avg']:,.2f}" if r["fv_avg"] is not None else "–"
            stale = "  STALE" if r["stale"] else ""
            print(f"  {r['ticker']:<7} {r['rating'] or '–':<11} FV {fv:<10} "
                  f"MoS {mos:<8} {r['coherence'] or '':<24} "
                  f"age {r['age_days']}d{stale}")
        return 0

    if args.compare:
        from .compare import MAX_TICKERS, build_compare_html
        from .ledger import Ledger
        from .pipeline import build_dashboard_data
        tickers = [t.strip().upper() for t in args.compare.split(",") if t.strip()]
        if not 2 <= len(tickers) <= MAX_TICKERS:
            _report_error(f"--compare needs 2–{MAX_TICKERS} tickers")
            return 2
        datas = []
        try:
            for t in tickers:
                print(f"  fetching {t}…", flush=True)
                datas.append(build_dashboard_data(
                    t, cache=Cache(enabled=not args.no_cache),
                    track="auto", years=args.years))
        except EdgarError as exc:
            _report_error(str(exc))
            return 2
        rows = {r["ticker"]: r for r in Ledger().list_verdicts()}
        out = args.out or ("_vs_".join(tickers) + "_compare.html")
        build_compare_html(datas, out, ledger_rows=rows)
        print(f"wrote {out}")
        return 0

    if args.gui or not args.ticker:
        from .gui import run_gui
        run_gui()
        return 0

    if config.UA_IS_PLACEHOLDER and sys.stderr is not None:
        print(f"warning: {config.UA_WARNING}", file=sys.stderr)

    from .pipeline import build_dashboard_data
    try:
        data = build_dashboard_data(
            args.ticker,
            cache=Cache(enabled=not args.no_cache),
            progress=lambda m: print(f"  {m}", flush=True),
            track=args.track,
            years=args.years,
        )
    except EdgarError as exc:
        _report_error(str(exc))
        return 2

    from .metrics import set_adjusted_ni
    if args.adjusted_ni is not None:
        set_adjusted_ni(data, args.adjusted_ni)
        if data.adjustment_burden is not None:
            flag = "  FLAG >20% (master §3.1)" if data.adjustment_burden > 0.20 else ""
            print(f"  adjustment burden {data.adjustment_burden * 100:.1f}%{flag}")
    if args.thesis:
        data.thesis = args.thesis
    if args.terminal_risk:
        data.terminal_risk = args.terminal_risk
    if args.non_op_investments is not None:
        data.non_op_investments = args.non_op_investments

    from .dashboard import (
        render_dashboard, render_health_report, render_unit_economics,
        render_valuation, render_verdict,
    )
    from .export import (
        export_fundamentals_csv, export_pdf, export_prices_csv, export_valuation_csv,
    )
    from .valuation import ValuationError
    from .verdict import build_verdict

    fig_main = render_dashboard(data, dpi=args.dpi)
    fig_unit = render_unit_economics(data, dpi=args.dpi)
    fig_health = render_health_report(data, dpi=args.dpi)
    fig_val = fig_verdict = res = verdict = None
    if args.value:
        try:
            res = _build_valuation_result(data, args)
            data.rating = args.rating or ""
            data.optionality = args.optionality or ""
            verdict = build_verdict(data, res._inputs, res,
                                    rating=data.rating,
                                    optionality=data.optionality)
            fig_val = render_valuation(data, res, dpi=args.dpi)
            fig_verdict = render_verdict(data, res, verdict, dpi=args.dpi)
        except ValuationError as exc:
            _report_error(str(exc))
            return 2

    stamp = data.generated.isoformat()
    years = data.display_years
    if args.png:
        out = args.out or f"{data.ticker}_{years}y_dashboard_{stamp}.png"
        base = out[:-4] if out.lower().endswith(".png") else out
        fig_main.savefig(out, dpi=args.dpi)
        print(f"wrote {out}")
        for fig, suffix in ((fig_unit, "_unit"), (fig_health, "_health"),
                            (fig_val, "_valuation"), (fig_verdict, "_verdict")):
            if fig is not None:
                fig.savefig(base + suffix + ".png", dpi=args.dpi)
                print(f"wrote {base}{suffix}.png")
    else:
        out = args.out or f"{data.ticker}_{years}y_report_{stamp}.pdf"
        if not out.lower().endswith(".pdf"):
            out += ".pdf"
        base = out[:-4]
        export_pdf([fig_main, fig_unit, fig_health, fig_val, fig_verdict], out)
        print(f"wrote {out} (A4)")

    if args.html is not None:
        from .interactive import build_html
        html_path = args.html or f"{data.ticker}_interactive_{stamp}.html"
        build_html(data, html_path, res=res, verdict=verdict)
        print(f"wrote {html_path}")

    if data.price_error:
        print(f"note: price sources unavailable ({data.price_error}); "
              "rendered fundamentals only")
    if res is not None:
        for c in res.cases:
            print(f"  {c.name:<4} FV ${c.fv_ps:,.2f}  MoS {c.mos * 100:+.1f}%")
        if res.implied_g is not None:
            print(f"  reverse DCF (§4.D): market implies g ≈ {res.implied_g * 100:.1f}%")
        if res.rate_build:
            print(f"  rate build: {res.rate_build}")
    if verdict is not None and verdict.fv_avg is not None:
        line = (f"  Phase 5: FV_avg ${verdict.fv_avg:,.2f}  "
                f"MoS {verdict.mos * 100:+.1f}%")
        if verdict.stressed_mos is not None:
            line += f"  stressed {verdict.stressed_mos * 100:+.1f}%"
        print(line)
        print(f"  rating gate: {verdict.coherence}")
        try:  # §5.7: no verdict leaves the session unlogged
            from .ledger import Ledger
            Ledger().upsert_verdict(data, res=res, verdict=verdict)
            print("  ledger updated (see --ledger)")
        except Exception:
            pass

    if args.csv:
        fpath = base + "_fundamentals.csv"
        export_fundamentals_csv(data, fpath)
        print(f"wrote {fpath}")
        if data.price_dates:
            ppath = base + "_prices.csv"
            export_prices_csv(data, ppath)
            print(f"wrote {ppath}")
        if res is not None:
            vpath = base + "_valuation.csv"
            export_valuation_csv(res, vpath)
            print(f"wrote {vpath}")

    if args.xlsx is not None:
        from .workbook import fill_workbook
        xlsx_path = args.xlsx or f"{data.ticker}_forensic_model_{stamp}.xlsx"
        report = fill_workbook(data, xlsx_path, res=res, verdict=verdict)
        print(f"wrote {xlsx_path} ({report.filled} blue cells filled)")
        print("  analyst cells remaining (judgment stays with you):")
        for sheet, cells, label, source in report.analyst_cells:
            print(f"    {sheet}!{cells:<8} {label} -> {source}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
