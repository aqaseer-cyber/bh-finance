"""Command-line entry point.

  python -m forensic_viz                    -> GUI
  python -m forensic_viz AAPL               -> dashboard + health-check PNGs
  python -m forensic_viz AAPL --csv         -> PNG + fundamentals/prices CSVs
  python -m forensic_viz --demo -o demo.png -> offline synthetic dashboard

  Intrinsic value (Bear/Base/Bull), e.g. a DCF with WACC 9%:
  python -m forensic_viz AAPL --value dcf --wacc 0.09 \
      --bear 0.02,0.02 --base 0.05,0.025 --bull 0.09,0.03
    each --bear/--base/--bull is method-specific, comma-separated:
      dcf    g0,g_term        (stage-1 growth, terminal growth)
      ri     roe,g0,g_term    (add --wacc for r_e)
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
    from .valuation import CaseInputs, ValuationError
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        raise ValuationError(f"case '{raw}' must be comma-separated numbers")
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


def _run_valuation(data, args, base_png: str, dpi: int) -> int:
    from .dashboard import render_valuation
    from .valuation import (
        CASE_NAMES, ValuationError, ValuationInputs, build_valuation,
    )
    method = args.value.lower()
    try:
        raws = {"Bear": args.bear, "Base": args.base, "Bull": args.bull}
        missing = [n for n, r in raws.items() if not r]
        if missing:
            raise ValuationError(
                f"provide --{'/--'.join(m.lower() for m in missing)} case assumptions")
        cases = {n: _parse_case(method, raws[n]) for n in CASE_NAMES}
        inputs = ValuationInputs(
            method=method, cases=cases,
            discount_rate=args.wacc, base_value=args.base_value, ex_sbc=args.ex_sbc)
        res = build_valuation(data, inputs)
    except ValuationError as exc:
        _report_error(str(exc))
        return 2
    out = base_png + "_valuation.png"
    render_valuation(data, res, out_path=out, dpi=dpi)
    print(f"wrote {out}")
    for c in res.cases:
        print(f"  {c.name:<4} FV ${c.fv_ps:,.2f}  MoS {c.mos * 100:+.1f}%")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="forensic-viz",
        description="10-year forensic stock dashboard from SEC EDGAR XBRL + daily prices.",
    )
    parser.add_argument("ticker", nargs="?", help="US-listed ticker, e.g. AAPL")
    parser.add_argument("-o", "--out", help="output PNG path")
    parser.add_argument("--csv", action="store_true",
                        help="also write fundamentals (and prices) CSVs next to the PNG")
    parser.add_argument("--demo", action="store_true",
                        help="render the offline synthetic demo company")
    parser.add_argument("--gui", action="store_true", help="launch the desktop app")
    parser.add_argument("--no-cache", action="store_true", help="bypass the local cache")
    parser.add_argument("--dpi", type=int, default=150)

    val = parser.add_argument_group("intrinsic value (Bear/Base/Bull)")
    val.add_argument("--value", choices=["dcf", "ri", "affo", "manual"],
                     help="run the intrinsic-value calculator with this method")
    val.add_argument("--wacc", type=float,
                     help="discount rate: WACC (dcf) or r_e (ri), e.g. 0.09")
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
    else:
        from .pipeline import build_dashboard_data
        try:
            data = build_dashboard_data(
                args.ticker,
                cache=Cache(enabled=not args.no_cache),
                progress=lambda m: print(f"  {m}", flush=True),
            )
        except EdgarError as exc:
            _report_error(str(exc))
            return 2

    from .dashboard import render_dashboard, render_health_report
    from .export import export_fundamentals_csv, export_prices_csv

    out = args.out or (
        f"{data.ticker}_{config.DISPLAY_YEARS}y_dashboard_{data.generated.isoformat()}.png")
    render_dashboard(data, out_path=out, dpi=args.dpi)
    print(f"wrote {out}")
    base = out[:-4] if out.lower().endswith(".png") else out
    health_out = base + "_health.png"
    render_health_report(data, out_path=health_out, dpi=args.dpi)
    print(f"wrote {health_out}")
    if data.price_error:
        print(f"note: price sources unavailable ({data.price_error}); "
              "rendered fundamentals only")

    if args.csv:
        fpath = base + "_fundamentals.csv"
        export_fundamentals_csv(data, fpath)
        print(f"wrote {fpath}")
        if data.price_dates:
            ppath = base + "_prices.csv"
            export_prices_csv(data, ppath)
            print(f"wrote {ppath}")

    if args.value:
        rc = _run_valuation(data, args, base, args.dpi)
        if rc:
            return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
