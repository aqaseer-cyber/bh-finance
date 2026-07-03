"""Command-line entry point.

  python -m forensic_viz                    -> GUI
  python -m forensic_viz AAPL               -> AAPL_5y_dashboard_<date>.png
  python -m forensic_viz AAPL --csv         -> PNG + fundamentals/prices CSVs
  python -m forensic_viz --demo -o demo.png -> offline synthetic dashboard
"""
from __future__ import annotations

import argparse
import sys

from . import config
from .cache import Cache
from .edgar import EdgarError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="forensic-viz",
        description="5-year stock performance dashboard from SEC EDGAR XBRL + daily prices.",
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
            print(f"error: {exc}", file=sys.stderr)
            return 2

    from .dashboard import render_dashboard
    from .export import export_fundamentals_csv, export_prices_csv

    out = args.out or f"{data.ticker}_5y_dashboard_{data.generated.isoformat()}.png"
    fig = render_dashboard(data, out_path=out, dpi=args.dpi)
    print(f"wrote {out}")
    if data.price_error:
        print(f"note: price sources unavailable ({data.price_error}); "
              "rendered fundamentals only")

    if args.csv:
        base = out[:-4] if out.lower().endswith(".png") else out
        fpath = base + "_fundamentals.csv"
        export_fundamentals_csv(data, fpath)
        print(f"wrote {fpath}")
        if data.price_dates:
            ppath = base + "_prices.csv"
            export_prices_csv(data, ppath)
            print(f"wrote {ppath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
