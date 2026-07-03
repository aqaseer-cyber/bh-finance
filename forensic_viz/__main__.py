"""Command-line entry point.

  python -m forensic_viz                     -> GUI
  python -m forensic_viz AAPL                -> AAPL_10y_report_<date>.pdf
  python -m forensic_viz AAPL --png --csv    -> per-page PNGs + CSVs
  python -m forensic_viz --demo -o demo.pdf  -> offline synthetic report

  Intrinsic value (Bear/Base/Bull); WACC auto-builds (live 10-Y UST + beta)
  when --wacc is omitted:
  python -m forensic_viz AAPL --value dcf \
      --bear 0.02,0.02 --base 0.05,0.025 --bull 0.09,0.03
    each --bear/--base/--bull is method-specific, comma-separated:
      dcf    g0,g_term        (stage-1 growth, terminal growth)
      ri     roe,g0,g_term    (r_e auto-built or via --wacc)
      affo   affo_per_share,target_yield
      manual fv_per_share
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
    missing = [n for n, r in raws.items() if not r]
    if missing:
        raise ValuationError(
            f"provide --{'/--'.join(m.lower() for m in missing)} case assumptions")
    cases = {n: _parse_case(method, raws[n]) for n in CASE_NAMES}
    inputs = ValuationInputs(
        method=method, cases=cases,
        discount_rate=args.wacc, base_value=args.base_value, ex_sbc=args.ex_sbc)
    return build_valuation(data, inputs)


def main(argv=None) -> int:
    from .metrics import TRACKS

    parser = argparse.ArgumentParser(
        prog="forensic-viz",
        description="10-year forensic stock report from SEC EDGAR XBRL + daily prices.",
    )
    parser.add_argument("ticker", nargs="?", help="US-listed ticker, e.g. AAPL")
    parser.add_argument("-o", "--out", help="output path (.pdf, or base name with --png)")
    parser.add_argument("--png", action="store_true",
                        help="write per-page PNGs instead of a single PDF")
    parser.add_argument("--csv", action="store_true",
                        help="also write fundamentals/prices (and valuation) CSVs")
    parser.add_argument("--demo", action="store_true",
                        help="render the offline synthetic demo company")
    parser.add_argument("--gui", action="store_true", help="launch the desktop app")
    parser.add_argument("--no-cache", action="store_true", help="bypass the local cache")
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--track", choices=list(TRACKS), default="auto",
                        help="logic track override (master Phase 1); auto = from SIC")
    parser.add_argument("--adjusted-ni", type=float,
                        help="fluff filter (§3.1): latest-FY non-GAAP net income in $ "
                             "from the earnings release; computes the adjustment burden")
    parser.add_argument("--thesis",
                        help="investment thesis (§2.4), printed on the unit-economics page")
    parser.add_argument("--terminal-risk",
                        help="terminal risk (§2.3, cite Item 1A), printed on the "
                             "unit-economics page; anchors the Phase-5 rating")

    val = parser.add_argument_group("intrinsic value (Bear/Base/Bull)")
    val.add_argument("--value", choices=["dcf", "ri", "affo", "manual"],
                     help="run the intrinsic-value calculator with this method")
    val.add_argument("--wacc", type=float,
                     help="discount rate override (fraction, e.g. 0.09); omitted = "
                          "auto-build from live 10-Y UST + regression beta")
    val.add_argument("--base-value", type=float,
                     help="override base: FCFF $ (dcf) or BV0 $ (ri)")
    val.add_argument("--ex-sbc", action="store_true",
                     help="dcf base on ex-SBC FCF (house §2b, Track B)")
    val.add_argument("--bear", help="Bear-case assumptions (method-specific, comma-separated)")
    val.add_argument("--base", help="Base-case assumptions")
    val.add_argument("--bull", help="Bull-case assumptions")
    args = parser.parse_args(argv)

    if args.gui or (not args.ticker and not args.demo):
        from .gui import run_gui
        run_gui()
        return 0

    if args.demo:
        from .demo_data import demo_dashboard_data
        data = demo_dashboard_data()
        if args.track != "auto":
            from .metrics import apply_track, compute_altman
            apply_track(data, args.track)
            compute_altman(data)
    else:
        from .pipeline import build_dashboard_data
        try:
            data = build_dashboard_data(
                args.ticker,
                cache=Cache(enabled=not args.no_cache),
                progress=lambda m: print(f"  {m}", flush=True),
                track=args.track,
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

    from .dashboard import (
        render_dashboard, render_health_report, render_unit_economics,
        render_valuation,
    )
    from .export import (
        export_fundamentals_csv, export_pdf, export_prices_csv, export_valuation_csv,
    )
    from .valuation import ValuationError

    fig_main = render_dashboard(data, dpi=args.dpi)
    fig_unit = render_unit_economics(data, dpi=args.dpi)
    fig_health = render_health_report(data, dpi=args.dpi)
    fig_val, res = None, None
    if args.value:
        try:
            res = _build_valuation_result(data, args)
            fig_val = render_valuation(data, res, dpi=args.dpi)
        except ValuationError as exc:
            _report_error(str(exc))
            return 2

    stamp = data.generated.isoformat()
    if args.png:
        out = args.out or f"{data.ticker}_{config.DISPLAY_YEARS}y_dashboard_{stamp}.png"
        base = out[:-4] if out.lower().endswith(".png") else out
        fig_main.savefig(out, dpi=args.dpi)
        print(f"wrote {out}")
        fig_unit.savefig(base + "_unit.png", dpi=args.dpi)
        print(f"wrote {base}_unit.png")
        fig_health.savefig(base + "_health.png", dpi=args.dpi)
        print(f"wrote {base}_health.png")
        if fig_val is not None:
            fig_val.savefig(base + "_valuation.png", dpi=args.dpi)
            print(f"wrote {base}_valuation.png")
    else:
        out = args.out or f"{data.ticker}_{config.DISPLAY_YEARS}y_report_{stamp}.pdf"
        if not out.lower().endswith(".pdf"):
            out += ".pdf"
        base = out[:-4]
        export_pdf([fig_main, fig_unit, fig_health, fig_val], out)
        print(f"wrote {out}")

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
    return 0


if __name__ == "__main__":
    sys.exit(main())
