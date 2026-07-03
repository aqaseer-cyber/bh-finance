"""Tkinter desktop app: type a ticker, get the 5-year forensic dashboard.

Network fetches run on a worker thread; all Tk and matplotlib work stays on
the main thread (results are handed back through a queue polled with after()).
"""
from __future__ import annotations

import math
import queue
import sys
import threading
import traceback
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from . import config
from .cache import Cache
from .dashboard import (
    FIG_W, render_dashboard, render_health_report, render_valuation,
)
from .demo_data import demo_dashboard_data
from .edgar import EdgarError
from .export import (
    export_fundamentals_csv, export_pdf, export_prices_csv, export_valuation_csv,
)
from .metrics import (
    TRACKS, DashboardData, apply_track, compute_altman, set_adjusted_ni,
)
from .pipeline import build_dashboard_data
from .valuation import (
    CASE_NAMES, METHODS, CaseInputs, ValuationError, ValuationInputs,
    build_valuation, suggest_method,
)

SCREEN_DPI = 100  # on-screen render; PNG export re-renders at 150


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(f"Forensic Stock Viz {config.APP_VERSION} — 5-year performance dashboard")
        w = min(1180, root.winfo_screenwidth() - 40)
        h = min(860, root.winfo_screenheight() - 80)
        root.geometry(f"{w}x{h}")
        root.minsize(700, 500)

        self.queue: "queue.Queue[tuple]" = queue.Queue()
        self.data: Optional[DashboardData] = None
        self.fig = None
        self.health_fig = None
        self.valuation_fig = None
        self.valuation_res = None
        self.canvases: list[FigureCanvasTkAgg] = []
        self.busy = False

        bar = ttk.Frame(root, padding=(10, 8))
        bar.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(bar, text="Ticker:").pack(side=tk.LEFT)
        self.ticker_var = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.ticker_var, width=10)
        entry.pack(side=tk.LEFT, padx=(6, 8))
        entry.bind("<Return>", lambda _e: self.analyze())
        entry.focus_set()
        ttk.Label(bar, text="Track:").pack(side=tk.LEFT, padx=(10, 4))
        self.track_var = tk.StringVar(value="auto")
        track_box = ttk.Combobox(bar, state="readonly", width=9,
                                 textvariable=self.track_var,
                                 values=list(TRACKS))
        track_box.pack(side=tk.LEFT)
        track_box.bind("<<ComboboxSelected>>", lambda _e: self._on_track_change())
        self.analyze_btn = ttk.Button(bar, text="Analyze", command=self.analyze)
        self.analyze_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.demo_btn = ttk.Button(bar, text="Offline demo", command=self.demo)
        self.demo_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.value_btn = ttk.Button(bar, text="Intrinsic value…",
                                     command=self.open_valuation, state=tk.DISABLED)
        self.value_btn.pack(side=tk.LEFT, padx=(16, 0))
        self.fluff_btn = ttk.Button(bar, text="Fluff filter…",
                                    command=self.fluff_filter, state=tk.DISABLED)
        self.fluff_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.save_btn = ttk.Button(bar, text="Save PDF…", command=self.save_pdf,
                                   state=tk.DISABLED)
        self.save_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.csv_btn = ttk.Button(bar, text="Export CSV…", command=self.export_csv,
                                  state=tk.DISABLED)
        self.csv_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.status_var = tk.StringVar(
            value="Enter a US-listed ticker (e.g. AAPL) and press Analyze.")
        ttk.Label(bar, textvariable=self.status_var, foreground="#52514e").pack(
            side=tk.LEFT, padx=(16, 0))

        # Scrollable viewport for the tall dashboard figure
        holder = ttk.Frame(root)
        holder.pack(fill=tk.BOTH, expand=True)
        self.view = tk.Canvas(holder, background="#f9f9f7", highlightthickness=0)
        vbar = ttk.Scrollbar(holder, orient=tk.VERTICAL, command=self.view.yview)
        hbar = ttk.Scrollbar(holder, orient=tk.HORIZONTAL, command=self.view.xview)
        self.view.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        vbar.pack(side=tk.RIGHT, fill=tk.Y)
        hbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.inner = ttk.Frame(self.view)
        self.inner_id = self.view.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._sync_scrollregion)
        self._wheel_accum = 0.0
        self.view.bind_all("<MouseWheel>", self._on_mousewheel)      # Windows/macOS
        self.view.bind_all("<Button-4>", self._on_mousewheel_linux)  # X11
        self.view.bind_all("<Button-5>", self._on_mousewheel_linux)

        self.root.after(120, self._poll_queue)

    # ------------------------------------------------------------ scrolling

    def _sync_scrollregion(self, _event=None):
        self.view.configure(scrollregion=self.view.bbox("all"))

    def _on_mousewheel(self, event):
        if sys.platform == "darwin":  # Aqua Tk reports small per-notch deltas
            self.view.yview_scroll(-event.delta, "units")
            return
        # Windows precision touchpads send |delta| < 120 per event; accumulate
        # so smooth scrolling still moves the view instead of truncating to 0.
        self._wheel_accum += event.delta
        steps = int(self._wheel_accum / 120)
        if steps:
            self._wheel_accum -= steps * 120
            self.view.yview_scroll(-steps * 3, "units")

    def _on_mousewheel_linux(self, event):
        self.view.yview_scroll(-3 if event.num == 4 else 3, "units")

    # -------------------------------------------------------------- actions

    def analyze(self):
        if self.busy:
            return
        ticker = self.ticker_var.get().strip().upper()
        if not ticker:
            messagebox.showinfo("Ticker required", "Enter a ticker symbol, e.g. AAPL.")
            return
        self._set_busy(True, f"Fetching data for {ticker}…")
        threading.Thread(target=self._worker, args=(ticker,), daemon=True).start()

    def demo(self):
        if self.busy:
            return
        self._set_busy(True, "Building offline demo…")
        threading.Thread(target=self._demo_worker, daemon=True).start()

    def _worker(self, ticker: str):
        try:
            data = build_dashboard_data(
                ticker,
                cache=Cache(),
                progress=lambda msg: self.queue.put(("status", msg)),
                track=self.track_var.get(),
            )
            self.queue.put(("data", data))
        except EdgarError as exc:
            self.queue.put(("error", str(exc)))
        except Exception:
            self.queue.put(("error", "Unexpected error:\n" + traceback.format_exc(limit=3)))

    def _demo_worker(self):
        try:
            data = demo_dashboard_data()
            if self.track_var.get() != "auto":
                apply_track(data, self.track_var.get())
                compute_altman(data)
            self.queue.put(("data", data))
        except Exception:
            self.queue.put(("error", "Demo failed:\n" + traceback.format_exc(limit=3)))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "status":
                    self.status_var.set(payload)
                elif kind == "data":
                    self._show(payload)
                elif kind == "error":
                    self._set_busy(False, "Failed.")
                    messagebox.showerror("Could not build dashboard", payload)
        except queue.Empty:
            pass
        except Exception:
            # a rendering failure must not kill the poll loop / lock the UI
            self._set_busy(False, "Failed.")
            messagebox.showerror(
                "Could not render dashboard", traceback.format_exc(limit=3))
        finally:
            self.root.after(120, self._poll_queue)

    def _show(self, data: DashboardData):
        self.status_var.set("Rendering…")
        self.root.update_idletasks()
        # fit the on-screen figure to the viewport width (PNG export re-renders
        # at full 150 dpi regardless), with the horizontal bar as the fallback
        viewport = self.view.winfo_width() or 1160
        dpi = max(70, min(SCREEN_DPI, int(viewport / FIG_W)))
        fig = render_dashboard(data, dpi=dpi)
        health_fig = render_health_report(data, dpi=dpi)
        for canvas in self.canvases:
            canvas.get_tk_widget().destroy()
        self.canvases = []
        self.data, self.fig, self.health_fig = data, fig, health_fig
        self.valuation_fig = None  # a new ticker invalidates any prior valuation
        self.valuation_res = None
        self._render_pages()
        note = ""
        if data.price_error:
            note = "  (price sources unavailable — fundamentals only)"
        self._set_busy(False, f"{data.company} — done.{note}")

    def _render_pages(self, scroll_to: str = "top"):
        """(Re)build the stacked canvases: dashboard, health, then valuation."""
        for canvas in self.canvases:
            canvas.get_tk_widget().destroy()
        self.canvases = []
        pages = [self.fig, self.health_fig]
        if self.valuation_fig is not None:
            pages.append(self.valuation_fig)
        for f in pages:
            canvas = FigureCanvasTkAgg(f, master=self.inner)
            canvas.draw()
            canvas.get_tk_widget().pack(pady=(0, 12))
            self.canvases.append(canvas)
        self.view.xview_moveto(0)
        # the scrollregion updates when `inner` re-configures; position after
        self.root.after(
            50, lambda: self.view.yview_moveto(0.0 if scroll_to == "top" else 1.0))

    def save_pdf(self):
        # pin: a run finishing behind the modal dialog must not swap these
        figs = [self.fig, self.health_fig, self.valuation_fig]
        data = self.data
        if figs[0] is None or data is None:
            return
        default = (f"{data.ticker}_{config.DISPLAY_YEARS}y_report_"
                   f"{data.generated.isoformat()}.pdf")
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf", initialfile=default,
            filetypes=[("PDF report", "*.pdf")])
        if not path:
            return
        export_pdf(figs, path)
        pages = sum(1 for f in figs if f is not None)
        self.status_var.set(f"Saved {pages}-page report: {path}")

    def export_csv(self):
        data = self.data
        if data is None:
            return
        default = f"{data.ticker}_5y_fundamentals_{data.generated.isoformat()}.csv"
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", initialfile=default,
            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        export_fundamentals_csv(data, path)
        written = [path]
        p = Path(path)
        if data.price_dates:
            price_path = str(p.with_name(p.stem + "_prices" + p.suffix))
            export_prices_csv(data, price_path)
            written.append(price_path)
        if self.valuation_res is not None:
            val_path = str(p.with_name(p.stem + "_valuation" + p.suffix))
            export_valuation_csv(self.valuation_res, val_path)
            written.append(val_path)
        self.status_var.set(f"Saved {len(written)} CSV(s): " + path)

    def open_valuation(self):
        if self.data is None or self.busy:
            return
        if self.data.last_close is None:
            messagebox.showinfo(
                "No price",
                "The margin of safety needs a current price, but the price "
                "sources were unavailable for this ticker. Re-run Analyze when "
                "prices are reachable.")
            return
        _ValuationDialog(self.root, self.data, self._on_valuation_done)

    def _on_valuation_done(self, fig, res):
        self.valuation_fig = fig
        self.valuation_res = res
        self._render_pages(scroll_to="bottom")  # show the new page, not page 1
        self.status_var.set(
            f"{self.data.company} — intrinsic value added below (page 3).")

    def _on_track_change(self):
        """Re-resolve the Logic Track and re-render the track-aware pages."""
        if self.data is None or self.busy:
            return
        apply_track(self.data, self.track_var.get())
        compute_altman(self.data)
        viewport = self.view.winfo_width() or 1160
        dpi = max(70, min(SCREEN_DPI, int(viewport / FIG_W)))
        self.health_fig = render_health_report(self.data, dpi=dpi)
        self._render_pages()
        self.status_var.set(
            f"{self.data.company} — {self.data.track.title()} track applied.")

    def fluff_filter(self):
        """Fluff filter (§3.1): analyst supplies the non-GAAP net income."""
        if self.data is None or self.busy:
            return
        gaap = None
        for v in reversed(self.data.net_income):
            if v is not None:
                gaap = v
                break
        adjusted = simpledialog.askfloat(
            "Fluff filter — adjustment burden (§3.1)",
            "Adjusted (non-GAAP) net income for the latest fiscal year, in $.\n"
            "From the earnings release — this figure is not in XBRL.\n"
            f"GAAP net income for reference: {gaap:,.0f}" if gaap is not None
            else "Adjusted (non-GAAP) net income for the latest fiscal year, in $.",
            parent=self.root, initialvalue=gaap)
        if adjusted is None:
            return
        set_adjusted_ni(self.data, adjusted)
        viewport = self.view.winfo_width() or 1160
        dpi = max(70, min(SCREEN_DPI, int(viewport / FIG_W)))
        self.health_fig = render_health_report(self.data, dpi=dpi)
        self._render_pages()
        if self.data.adjustment_burden is not None:
            burden = self.data.adjustment_burden
            flag = "  FLAG >20% (master §3.1)" if burden > 0.20 else ""
            self.status_var.set(f"Adjustment burden {burden * 100:.1f}%{flag} — "
                                "see the health page KPI row.")

    def _set_busy(self, busy: bool, status: str):
        self.busy = busy
        state = tk.DISABLED if busy else tk.NORMAL
        self.analyze_btn.configure(state=state)
        self.demo_btn.configure(state=state)
        if busy:
            for b in (self.save_btn, self.csv_btn, self.value_btn, self.fluff_btn):
                b.configure(state=tk.DISABLED)
        elif self.data is not None:
            for b in (self.save_btn, self.csv_btn, self.value_btn, self.fluff_btn):
                b.configure(state=tk.NORMAL)
        self.status_var.set(status)


# Per-method case fields: (attribute, label, unit). unit "%" fields are entered
# in percent (9 = 9%, 160 = 160%); "$" fields are plain dollars. The dialog
# builds a Bear/Base/Bull row for each.
_METHOD_FIELDS = {
    "dcf": [("g0", "Stage-1 growth g₀", "%"), ("g_term", "Terminal growth g", "%")],
    "ri": [("roe", "Sustainable ROE", "%"), ("g0", "Book growth g₀", "%"),
           ("g_term", "Terminal growth g", "%")],
    "affo": [("affo_ps", "AFFO / share", "$"), ("target_yield", "Target AFFO yield", "%")],
    "manual": [("fv_ps", "FV / share", "$")],
}
_METHOD_HELP = {
    "dcf": "FCFF 2-stage DCF, 10-year linear fade. WACC is pre-filled from the "
           "automated §4.0 build (live 10-Y UST + regression β) — edit to "
           "override. Base FCFF defaults to latest-FY FCF + after-tax interest; "
           "tick ex-SBC for the Track-B basis.",
    "ri": "Residual income at r_e (pre-filled from the automated build; edit to "
          "override). BV₀ defaults to latest reported equity. Enter each "
          "case's sustainable ROE and book-growth path.",
    "affo": "REIT AFFO-yield cross-check. AFFO per share and target yield are "
            "analyst-supplied (the FFO→AFFO bridge isn't in XBRL).",
    "manual": "SOTP / external model: enter the FV per share you computed "
              "elsewhere; the app returns the margin of safety.",
}


def _parse_field(raw: str, is_pct: bool) -> Optional[float]:
    """Percent fields are entered in percent units (9 → 0.09, 160 → 1.6); a
    trailing % is tolerated. Dollar/count fields are plain floats. No magnitude
    guessing — an unambiguous convention so a legitimate 160% ROE is never
    silently divided down to 1.6%."""
    raw = raw.strip().rstrip("%").strip()
    if not raw:
        return None
    v = float(raw)
    if not math.isfinite(v):
        raise ValueError("value must be finite")
    return v / 100.0 if is_pct else v


class _ValuationDialog(tk.Toplevel):
    """Modal: pick a method, enter Bear/Base/Bull assumptions, render page 3."""

    def __init__(self, parent, data: DashboardData, on_done):
        super().__init__(parent)
        self.data = data
        self.on_done = on_done
        self.title("Intrinsic value — Bear / Base / Bull")
        self.transient(parent)
        self.resizable(False, False)
        self.method_var = tk.StringVar(value=suggest_method(data.track))
        self.wacc_var = tk.StringVar()
        self.base_var = tk.StringVar()
        self.exsbc_var = tk.BooleanVar(value=False)
        self.cell_vars: dict = {}

        pad = {"padx": 10, "pady": 4}
        top = ttk.Frame(self, padding=(12, 12))
        top.pack(fill=tk.BOTH, expand=True)

        ttk.Label(top, text="Method / category:").grid(row=0, column=0, sticky="w", **pad)
        method_box = ttk.Combobox(top, state="readonly", width=44,
                                  values=[METHODS[m] for m in _METHOD_FIELDS])
        method_box.grid(row=0, column=1, columnspan=3, sticky="w", **pad)
        self._method_keys = list(_METHOD_FIELDS)
        method_box.current(self._method_keys.index(self.method_var.get()))
        method_box.bind("<<ComboboxSelected>>",
                        lambda _e: self._on_method(method_box.current()))

        self.suggested_lbl = ttk.Label(
            top, foreground="#52514e",
            text=f"Pre-selected for the {data.track.title()} track "
                 f"(SIC {data.sic_code or '—'}); override if the economic "
                 "engine differs.")
        self.suggested_lbl.grid(row=1, column=0, columnspan=4, sticky="w", padx=10)

        self.help_lbl = ttk.Label(top, foreground="#52514e", wraplength=560,
                                  justify="left")
        self.help_lbl.grid(row=2, column=0, columnspan=4, sticky="w", **pad)
        ttk.Label(top, foreground="#898781",
                  text="Percent fields (%) are entered in percent: 9 = 9%, 160 = 160%. "
                       "Dollar fields ($) are plain amounts.").grid(
            row=5, column=0, columnspan=4, sticky="w", padx=10, pady=(2, 0))

        self.rate_frame = ttk.Frame(top)
        self.rate_frame.grid(row=3, column=0, columnspan=4, sticky="w", padx=6)
        self.wacc_lbl = ttk.Label(self.rate_frame, text="WACC:")
        self.wacc_lbl.pack(side=tk.LEFT, padx=(4, 4))
        ttk.Entry(self.rate_frame, textvariable=self.wacc_var, width=8).pack(side=tk.LEFT)
        self.base_lbl = ttk.Label(self.rate_frame, text="Base FCFF $ (optional):")
        self.base_lbl.pack(side=tk.LEFT, padx=(14, 4))
        ttk.Entry(self.rate_frame, textvariable=self.base_var, width=16).pack(side=tk.LEFT)
        self.exsbc_chk = ttk.Checkbutton(self.rate_frame, text="ex-SBC base",
                                         variable=self.exsbc_var)
        self.exsbc_chk.pack(side=tk.LEFT, padx=(14, 0))

        self.grid_frame = ttk.Frame(top)
        self.grid_frame.grid(row=4, column=0, columnspan=4, sticky="w", pady=(8, 4))

        btns = ttk.Frame(top)
        btns.grid(row=6, column=0, columnspan=4, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(btns, text="Compute", command=self._compute).pack(
            side=tk.RIGHT, padx=(0, 8))

        self._on_method(self._method_keys.index(self.method_var.get()))
        self.bind("<Return>", lambda _e: self._compute())
        self.grab_set()

    def _method_key(self) -> str:
        return self.method_var.get()

    def _on_method(self, index: int):
        method = self._method_keys[index]
        self.method_var.set(method)
        # Clear the rate/base entries so a value typed for one method can't leak
        # into another (e.g. a DCF Base FCFF being read as an RI book value),
        # then prefill the rate from the automated §4.0 build (editable).
        self.wacc_var.set("")
        self.base_var.set("")
        build = getattr(self.data, "wacc_build", None)
        if build is not None and method in ("dcf", "ri"):
            rate = build.wacc if method == "dcf" else build.r_e
            if rate is not None:
                self.wacc_var.set(f"{rate * 100:.2f}")
        self.help_lbl.configure(text=_METHOD_HELP[method])
        needs_rate = method in ("dcf", "ri")
        for w in (self.wacc_lbl, self.base_lbl):
            w.configure(state=tk.NORMAL if needs_rate else tk.DISABLED)
        self.wacc_lbl.configure(
            text="WACC (%, auto-built):" if method == "dcf" else "r_e (%, auto-built):")
        self.base_lbl.configure(
            text="Base FCFF $ (optional):" if method == "dcf"
            else "BV₀ $ (optional):")
        show_rate = "normal" if needs_rate else "hidden"
        for child in self.rate_frame.winfo_children():
            child.configure(state=tk.NORMAL if needs_rate else tk.DISABLED)
        self.exsbc_chk.configure(state=tk.NORMAL if method == "dcf" else tk.DISABLED)

        for w in self.grid_frame.winfo_children():
            w.destroy()
        self.cell_vars = {}
        fields = _METHOD_FIELDS[method]
        ttk.Label(self.grid_frame, text="", width=10).grid(row=0, column=0)
        for col, name in enumerate(CASE_NAMES, start=1):
            ttk.Label(self.grid_frame, text=name, width=12,
                      font=("Segoe UI", 9, "bold")).grid(row=0, column=col, padx=4)
        for r, (attr, label, hint) in enumerate(fields, start=1):
            ttk.Label(self.grid_frame, text=f"{label} ({hint})").grid(
                row=r, column=0, sticky="w", padx=(4, 8), pady=3)
            for col, name in enumerate(CASE_NAMES, start=1):
                var = tk.StringVar()
                self.cell_vars[(name, attr)] = var
                ttk.Entry(self.grid_frame, textvariable=var, width=12).grid(
                    row=r, column=col, padx=4, pady=3)

    def _compute(self):
        method = self._method_key()
        fields = _METHOD_FIELDS[method]
        try:
            cases = {}
            for name in CASE_NAMES:
                kwargs = {}
                for attr, label, unit in fields:
                    raw = self.cell_vars[(name, attr)].get()
                    val = _parse_field(raw, unit == "%")
                    if val is None:
                        raise ValuationError(f"{name}: {label} is required.")
                    kwargs[attr] = val
                cases[name] = CaseInputs(**kwargs)
            rate, base = None, None
            if method in ("dcf", "ri"):  # only these read the rate/base fields
                rate = _parse_field(self.wacc_var.get(), True)
                base = _parse_field(self.base_var.get(), False)  # a $ amount
            inputs = ValuationInputs(
                method=method, cases=cases, discount_rate=rate,
                base_value=base, ex_sbc=self.exsbc_var.get())
            res = build_valuation(self.data, inputs)
        except ValuationError as exc:
            messagebox.showerror("Check the inputs", str(exc), parent=self)
            return
        except ValueError as exc:
            messagebox.showerror("Check the inputs", f"Numeric field error: {exc}",
                                 parent=self)
            return
        try:  # rendering must not fail silently and strand the modal open
            viewport = self.master.winfo_width() or 1160
            dpi = max(70, min(SCREEN_DPI, int(viewport / FIG_W)))
            fig = render_valuation(self.data, res, dpi=dpi)
            self.on_done(fig, res)
        except Exception:
            messagebox.showerror("Could not render the valuation page",
                                 traceback.format_exc(limit=3), parent=self)
            return
        self.destroy()


def run_gui():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")  # native look on Windows
    except tk.TclError:
        pass
    App(root)
    root.mainloop()
