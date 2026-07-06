"""Tkinter desktop app: the five-phase forensic report cockpit.

Layout: a control sidebar (inputs + actions + status) and a tabbed viewer —
one tab per report page (Dashboard / Unit economics / Health / Valuation /
Verdict). Network fetches run on a worker thread; all Tk and matplotlib work
stays on the main thread (results come back through a queue). The
"Interactive ↗" action writes the self-contained plotly HTML report and
opens it in the default browser.
"""
from __future__ import annotations

import math
import queue
import sys
import tempfile
import threading
import traceback
import webbrowser
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from . import config
from . import palette as P
from .cache import Cache
from .dashboard import (
    FIG_W, render_dashboard, render_health_report, render_unit_economics,
    render_valuation, render_verdict,
)
from .edgar import EdgarError
from .export import export_pdf
from .model_export import export_financial_model
from .compare import MAX_TICKERS, build_compare_html
from .interactive import build_html
from .ledger import Ledger
from .metrics import (
    TRACKS, DashboardData, apply_track, compute_altman, set_adjusted_ni,
)
from .pipeline import build_dashboard_data
from .valuation import (
    CASE_NAMES, METHODS, CaseInputs, ValuationError, ValuationInputs,
    build_valuation, suggest_method,
)
from .verdict import RATINGS, build_verdict
from .workbook import fill_workbook

SCREEN_DPI = 100  # on-screen render; exports re-render at 150
YEAR_CHOICES = ("3", "5", "7", "10")
PAGES = ("Dashboard", "Unit economics", "Health checks", "Valuation", "Verdict")


def apply_brand_theme(root: tk.Tk) -> None:
    """House brand skin (Colour Palette 07): forest sidebar, cream page,
    amber accent. Built on 'clam' — the one ttk theme that honours colour
    options on every platform (the native Windows theme ignores them)."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        return
    root.configure(background=P.PAGE)
    style.configure(".", background=P.PAGE, foreground=P.INK_PRIMARY,
                    bordercolor=P.BASELINE, focuscolor=P.GUI_ACCENT,
                    font=(P.FONT_STACK[0], 9))
    style.configure("TFrame", background=P.PAGE)
    style.configure("TLabel", background=P.PAGE, foreground=P.INK_PRIMARY)
    style.configure("Secondary.TLabel", foreground=P.INK_SECONDARY)
    style.configure("Muted.TLabel", foreground=P.INK_MUTED)
    # sidebar family (forest)
    style.configure("Side.TFrame", background=P.GUI_SIDEBAR_BG)
    style.configure("Side.TLabel", background=P.GUI_SIDEBAR_BG,
                    foreground=P.GUI_SIDEBAR_FG)
    style.configure("SideMuted.TLabel", background=P.GUI_SIDEBAR_BG,
                    foreground=P.GUI_SIDEBAR_MUTED)
    style.configure("Side.TSeparator", background=P.GUI_SIDEBAR_BTN_ACTIVE)
    style.configure("Side.TButton", background=P.GUI_SIDEBAR_BTN,
                    foreground=P.GUI_SIDEBAR_FG, borderwidth=0, padding=6)
    style.map("Side.TButton",
              background=[("disabled", P.GUI_SIDEBAR_BG),
                          ("pressed", P.GUI_SIDEBAR_BTN_ACTIVE),
                          ("active", P.GUI_SIDEBAR_BTN_ACTIVE)],
              foreground=[("disabled", P.GUI_SIDEBAR_MUTED)])
    style.configure("Accent.TButton", background=P.GUI_ACCENT,
                    foreground=P.GUI_ACCENT_FG, borderwidth=0, padding=6)
    style.map("Accent.TButton",
              background=[("disabled", P.GUI_SIDEBAR_BTN),
                          ("pressed", P.GUI_ACCENT_ACTIVE),
                          ("active", P.GUI_ACCENT_ACTIVE)],
              foreground=[("disabled", P.GUI_SIDEBAR_MUTED)])
    # tabs
    style.configure("TNotebook", background=P.PAGE, borderwidth=0)
    style.configure("TNotebook.Tab", background=P.PAGE,
                    foreground=P.INK_SECONDARY, padding=(14, 6))
    style.map("TNotebook.Tab",
              background=[("selected", P.SURFACE)],
              foreground=[("selected", P.INK_PRIMARY),
                          ("disabled", P.INK_MUTED)])
    # tables & inputs
    style.configure("Treeview", background=P.SURFACE, foreground=P.INK_PRIMARY,
                    fieldbackground=P.SURFACE, bordercolor=P.GRIDLINE)
    style.configure("Treeview.Heading", background=P.GUI_SIDEBAR_BG,
                    foreground=P.GUI_SIDEBAR_FG, relief="flat")
    style.map("Treeview.Heading", background=[("active", P.GUI_SIDEBAR_BTN)])
    style.map("Treeview", background=[("selected", P.SERIES[3])],
              foreground=[("selected", P.GUI_ACCENT_FG)])
    for w in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(w, fieldbackground="#ffffff",
                        foreground=P.INK_PRIMARY, bordercolor=P.BASELINE)
    style.map("TCombobox", fieldbackground=[("readonly", "#ffffff")])


class _ScrollTab(ttk.Frame):
    """A notebook tab hosting one matplotlib figure in a scrollable viewport."""

    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, background=P.PAGE, highlightthickness=0)
        vbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.canvas.yview)
        hbar = ttk.Scrollbar(self, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        vbar.pack(side=tk.RIGHT, fill=tk.Y)
        hbar.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.inner = ttk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.fig_canvas: Optional[FigureCanvasTkAgg] = None

    def show(self, fig) -> None:
        if self.fig_canvas is not None:
            self.fig_canvas.get_tk_widget().destroy()
            self.fig_canvas = None
        if fig is None:
            return
        self.fig_canvas = FigureCanvasTkAgg(fig, master=self.inner)
        self.fig_canvas.draw()
        self.fig_canvas.get_tk_widget().pack()
        self.canvas.yview_moveto(0)
        self.canvas.xview_moveto(0)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(f"Forensic Stock Viz {config.APP_VERSION} — five-phase forensic report")
        w = min(1280, root.winfo_screenwidth() - 40)
        h = min(880, root.winfo_screenheight() - 80)
        root.geometry(f"{w}x{h}")
        root.minsize(860, 560)

        self.queue: "queue.Queue[tuple]" = queue.Queue()
        self.data: Optional[DashboardData] = None
        self.figs = {name: None for name in PAGES}
        self.valuation_res = None
        self.verdict = None
        self.busy = False
        self._wheel_accum = 0.0

        # ---------------- sidebar (controls, forest brand panel) ----------------
        side = ttk.Frame(root, padding=(12, 12), style="Side.TFrame")
        side.pack(side=tk.LEFT, fill=tk.Y)

        ttk.Label(side, text="Ticker", style="Side.TLabel").pack(anchor="w")
        self.ticker_var = tk.StringVar()
        entry = ttk.Entry(side, textvariable=self.ticker_var, width=14)
        entry.pack(anchor="w", pady=(2, 8))
        entry.bind("<Return>", lambda _e: self.analyze())
        entry.focus_set()

        row = ttk.Frame(side, style="Side.TFrame")
        row.pack(anchor="w", pady=(0, 8))
        ttk.Label(row, text="Years", style="Side.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Label(row, text="Track", style="Side.TLabel").grid(
            row=0, column=1, sticky="w", padx=(10, 0))
        self.years_var = tk.StringVar(value="10")
        ttk.Combobox(row, state="readonly", width=4, textvariable=self.years_var,
                     values=list(YEAR_CHOICES)).grid(row=1, column=0, sticky="w")
        self.track_var = tk.StringVar(value="auto")
        track_box = ttk.Combobox(row, state="readonly", width=9,
                                 textvariable=self.track_var, values=list(TRACKS))
        track_box.grid(row=1, column=1, sticky="w", padx=(10, 0))
        track_box.bind("<<ComboboxSelected>>", lambda _e: self._on_track_change())

        self.analyze_btn = ttk.Button(side, text="Analyze", command=self.analyze,
                                      style="Accent.TButton")
        self.analyze_btn.pack(fill=tk.X, pady=(2, 4))
        self.compare_btn = ttk.Button(side, text="Compare…", command=self.compare,
                                      style="Side.TButton")
        self.compare_btn.pack(fill=tk.X, pady=(0, 10))

        ttk.Separator(side, style="Side.TSeparator").pack(fill=tk.X, pady=6)
        self.value_btn = ttk.Button(side, text="Intrinsic value…",
                                    command=self.open_valuation, state=tk.DISABLED,
                                    style="Side.TButton")
        self.value_btn.pack(fill=tk.X, pady=2)
        self.inputs_btn = ttk.Button(side, text="Analyst inputs…",
                                     command=self.analyst_inputs, state=tk.DISABLED,
                                     style="Side.TButton")
        self.inputs_btn.pack(fill=tk.X, pady=2)

        ttk.Separator(side, style="Side.TSeparator").pack(fill=tk.X, pady=6)
        self.html_btn = ttk.Button(side, text="Interactive report ↗",
                                   command=self.open_interactive, state=tk.DISABLED,
                                   style="Side.TButton")
        self.html_btn.pack(fill=tk.X, pady=2)
        self.save_btn = ttk.Button(side, text="Save PDF (A4)…",
                                   command=self.save_pdf, state=tk.DISABLED,
                                   style="Side.TButton")
        self.save_btn.pack(fill=tk.X, pady=2)
        self.csv_btn = ttk.Button(side, text="Financial model…",
                                  command=self.export_model, state=tk.DISABLED,
                                  style="Side.TButton")
        self.csv_btn.pack(fill=tk.X, pady=2)
        self.xlsx_btn = ttk.Button(side, text="Fill workbook…",
                                   command=self.fill_workbook, state=tk.DISABLED,
                                   style="Side.TButton")
        self.xlsx_btn.pack(fill=tk.X, pady=2)

        _start_msg = ("Enter a US-listed ticker (e.g. AAPL) and press Analyze."
                      if not config.UA_IS_PLACEHOLDER else config.UA_WARNING)
        self.status_var = tk.StringVar(value=_start_msg)
        ttk.Label(side, textvariable=self.status_var, style="Side.TLabel",
                  wraplength=160, justify="left").pack(
            side=tk.BOTTOM, anchor="w", pady=(12, 0))

        # ---------------- tabbed viewer ----------------
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.ledger = Ledger()
        self._build_watchlist_tab()
        self.tabs = {}
        for name in PAGES:
            tab = _ScrollTab(self.notebook)
            self.tabs[name] = tab
            self.notebook.add(tab, text=name, state=tk.DISABLED)
        self.refresh_watchlist()

        root.bind_all("<MouseWheel>", self._on_mousewheel)      # Windows/macOS
        root.bind_all("<Button-4>", self._on_mousewheel_linux)  # X11
        root.bind_all("<Button-5>", self._on_mousewheel_linux)
        self.root.after(120, self._poll_queue)

    # ------------------------------------------------------------ watchlist

    def _build_watchlist_tab(self):
        frame = ttk.Frame(self.notebook, padding=(8, 8))
        self.notebook.add(frame, text="Watchlist")
        cols = ("ticker", "rating", "fv", "mos", "smos", "price", "asof",
                "age", "gate", "trig")
        heads = ("Ticker", "Rating", "FV avg", "MoS", "Stressed", "P₀",
                 "As of", "Age (d)", "Gate", "Open trig")
        widths = (70, 80, 80, 70, 70, 70, 90, 60, 150, 70)
        self.tree = ttk.Treeview(frame, columns=cols, show="headings",
                                 selectmode="browse")
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="w")
        self.tree.tag_configure("stale", foreground=P.NEGATIVE)
        vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-1>", lambda _e: self._rerun_selected())
        btns = ttk.Frame(frame)
        btns.pack(side=tk.BOTTOM, anchor="w", pady=(6, 0))
        ttk.Button(btns, text="Re-run selected",
                   command=self._rerun_selected).pack(side=tk.LEFT)
        ttk.Button(btns, text="Remove selected",
                   command=self._remove_selected).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(btns, style="Muted.TLabel",
                  text="Verdict ledger (§5.7) — rows log automatically when a "
                       "valuation runs; red = stale (> ~5 trading days, house §8). "
                       "Double-click to re-run.").pack(side=tk.LEFT, padx=(14, 0))

    def refresh_watchlist(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for rec in self.ledger.list_verdicts():
            def pct(v):
                return f"{v * 100:+.1f}%" if v is not None else "–"
            self.tree.insert("", tk.END, values=(
                rec["ticker"], rec["rating"] or "–",
                f"${rec['fv_avg']:,.2f}" if rec["fv_avg"] is not None else "–",
                pct(rec["mos"]), pct(rec["stressed_mos"]),
                f"${rec['price']:,.2f}" if rec["price"] is not None else "–",
                rec["price_date"] or "–",
                rec["age_days"] if rec["age_days"] is not None else "–",
                rec["coherence"] or "–", rec["open_triggers"] or "",
            ), tags=("stale",) if rec["stale"] else ())

    def _selected_ticker(self) -> Optional[str]:
        sel = self.tree.selection()
        if not sel:
            return None
        return str(self.tree.item(sel[0], "values")[0])

    def _rerun_selected(self):
        ticker = self._selected_ticker()
        if ticker and not self.busy:
            self.ticker_var.set(ticker)
            self.analyze()

    def _remove_selected(self):
        ticker = self._selected_ticker()
        if ticker and messagebox.askyesno(
                "Remove from ledger",
                f"Remove {ticker} and its triggers from the verdict ledger?"):
            self.ledger.remove(ticker)
            self.refresh_watchlist()

    # -------------------------------------------------------------- compare

    def compare(self):
        if self.busy:
            return
        from tkinter import simpledialog
        raw = simpledialog.askstring(
            "Compare tickers",
            f"Enter 2–{MAX_TICKERS} tickers, comma-separated (e.g. AAPL, MSFT):",
            parent=self.root)
        if not raw:
            return
        tickers = [t.strip().upper() for t in raw.replace(";", ",").split(",")
                   if t.strip()][:MAX_TICKERS]
        if len(tickers) < 2:
            messagebox.showinfo("Compare", "Enter at least two tickers.")
            return
        self._set_busy(True, f"Comparing {', '.join(tickers)}…")
        threading.Thread(target=self._compare_worker, args=(tickers,),
                         daemon=True).start()

    def _compare_worker(self, tickers):
        try:
            datas = []
            for t in tickers:
                self.queue.put(("status", f"Fetching {t}…"))
                datas.append(build_dashboard_data(
                    t, cache=Cache(),
                    progress=lambda m: None,
                    track="auto", years=int(self.years_var.get())))
            rows = {r["ticker"]: r for r in Ledger().list_verdicts()}  # own conn (thread)
            out = Path(tempfile.gettempdir()) / (
                "_vs_".join(tickers) + "_compare.html")
            build_compare_html(datas, str(out), ledger_rows=rows)
            self.queue.put(("compare", str(out)))
        except EdgarError as exc:
            self.queue.put(("error", str(exc)))
        except Exception:
            self.queue.put(("error", "Compare failed:\n"
                            + traceback.format_exc(limit=3)))

    # ------------------------------------------------------------ scrolling

    def _current_canvas(self) -> Optional[tk.Canvas]:
        try:
            name = self.notebook.tab(self.notebook.select(), "text")
            return self.tabs[name].canvas
        except (tk.TclError, KeyError):
            return None

    def _on_mousewheel(self, event):
        canvas = self._current_canvas()
        if canvas is None:
            return
        if sys.platform == "darwin":
            canvas.yview_scroll(-event.delta, "units")
            return
        self._wheel_accum += event.delta
        steps = int(self._wheel_accum / 120)
        if steps:
            self._wheel_accum -= steps * 120
            canvas.yview_scroll(-steps * 3, "units")

    def _on_mousewheel_linux(self, event):
        canvas = self._current_canvas()
        if canvas is not None:
            canvas.yview_scroll(-3 if event.num == 4 else 3, "units")

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

    def _worker(self, ticker: str):
        try:
            data = build_dashboard_data(
                ticker,
                cache=Cache(),
                progress=lambda msg: self.queue.put(("status", msg)),
                track=self.track_var.get(),
                years=int(self.years_var.get()),
            )
            self.queue.put(("data", data))
        except EdgarError as exc:
            self.queue.put(("error", str(exc)))
        except Exception:
            self.queue.put(("error", "Unexpected error:\n" + traceback.format_exc(limit=3)))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "status":
                    self.status_var.set(payload)
                elif kind == "data":
                    self._show(payload)
                elif kind == "compare":
                    self._set_busy(False, "Comparison opened in the browser.")
                    webbrowser.open(Path(payload).as_uri())
                elif kind == "error":
                    self._set_busy(False, "Failed.")
                    messagebox.showerror("Could not build report", payload)
        except queue.Empty:
            pass
        except Exception:
            self._set_busy(False, "Failed.")
            messagebox.showerror("Could not render report",
                                 traceback.format_exc(limit=3))
        finally:
            self.root.after(120, self._poll_queue)

    def _screen_dpi(self) -> int:
        viewport = self.notebook.winfo_width() or 1060
        return max(70, min(SCREEN_DPI, int((viewport - 30) / FIG_W)))

    def _show(self, data: DashboardData):
        self.status_var.set("Rendering…")
        self.root.update_idletasks()
        dpi = self._screen_dpi()
        self.data = data
        self.figs["Dashboard"] = render_dashboard(data, dpi=dpi)
        self.figs["Unit economics"] = render_unit_economics(data, dpi=dpi)
        self.figs["Health checks"] = render_health_report(data, dpi=dpi)
        self.figs["Valuation"] = None
        self.figs["Verdict"] = None
        self.valuation_res = None
        self.verdict = None
        self._refresh_tabs(select="Dashboard")
        note = ("  (price sources unavailable — fundamentals only)"
                if data.price_error else "")
        self._set_busy(False, f"{data.company} — done.{note}")

    def _refresh_tabs(self, select: Optional[str] = None):
        for name in PAGES:
            fig = self.figs.get(name)
            self.tabs[name].show(fig)
            self.notebook.tab(self.tabs[name],
                              state=tk.NORMAL if fig is not None else tk.DISABLED)
        if select and self.figs.get(select) is not None:
            self.notebook.select(self.tabs[select])

    def _on_track_change(self):
        if self.data is None or self.busy:
            return
        apply_track(self.data, self.track_var.get())
        compute_altman(self.data)
        dpi = self._screen_dpi()
        self.figs["Unit economics"] = render_unit_economics(self.data, dpi=dpi)
        self.figs["Health checks"] = render_health_report(self.data, dpi=dpi)
        self._refresh_tabs()
        self.status_var.set(
            f"{self.data.company} — {self.data.track.title()} track applied.")

    def open_valuation(self):
        if self.data is None or self.busy:
            return
        if self.data.last_close is None:
            messagebox.showinfo(
                "No price",
                "The margin of safety needs a current price, but the price "
                "sources were unavailable for this ticker.")
            return
        _ValuationDialog(self.root, self.data, self._on_valuation_done)

    def _on_valuation_done(self, fig, res, verdict_fig, verdict):
        self.figs["Valuation"] = fig
        self.figs["Verdict"] = verdict_fig
        self.valuation_res = res
        self.verdict = verdict
        try:  # §5.7: no verdict leaves the session unlogged
            self.ledger.upsert_verdict(self.data, res=res, verdict=verdict)
            self.refresh_watchlist()
        except Exception:
            pass  # the ledger is a convenience store, never a blocker
        self._refresh_tabs(select="Valuation")
        gate = f" · rating gate: {verdict.coherence}" if verdict is not None else ""
        self.status_var.set(f"Intrinsic value + verdict ready (ledger updated).{gate}")

    def analyst_inputs(self):
        if self.data is None or self.busy:
            return
        _AnalystInputsDialog(self.root, self.data, self._on_analyst_inputs)

    def _on_analyst_inputs(self):
        dpi = self._screen_dpi()
        self.figs["Unit economics"] = render_unit_economics(self.data, dpi=dpi)
        self.figs["Health checks"] = render_health_report(self.data, dpi=dpi)
        self._refresh_tabs(select="Unit economics")
        note = ""
        if self.data.adjustment_burden is not None:
            burden = self.data.adjustment_burden
            flag = " FLAG >20%" if burden > 0.20 else ""
            note = f"  Adjustment burden {burden * 100:.1f}%{flag}."
        self.status_var.set(f"Analyst inputs applied.{note}")

    def open_interactive(self):
        if self.data is None or self.busy:
            return
        out = Path(tempfile.gettempdir()) / (
            f"{self.data.ticker}_interactive_{self.data.generated.isoformat()}.html")
        try:
            build_html(self.data, str(out), res=self.valuation_res,
                       verdict=self.verdict)
        except Exception:
            messagebox.showerror("Interactive report failed",
                                 traceback.format_exc(limit=3))
            return
        webbrowser.open(out.as_uri())
        self.status_var.set(f"Interactive report opened: {out.name}")

    def save_pdf(self):
        figs = [self.figs.get(n) for n in PAGES]
        data = self.data
        if figs[0] is None or data is None:
            return
        default = (f"{data.ticker}_{data.display_years}y_report_"
                   f"{data.generated.isoformat()}.pdf")
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf", initialfile=default,
            filetypes=[("PDF report (A4)", "*.pdf")])
        if not path:
            return
        export_pdf(figs, path)
        pages = sum(1 for f in figs if f is not None)
        self.status_var.set(f"Saved {pages}-page A4 report: {path}")

    def export_model(self):
        """One-sheet three-statement model: annual + quarterly + LTM."""
        data = self.data
        if data is None:
            return
        default = (f"{data.ticker}_financial_model_"
                   f"{data.generated.isoformat()}.xlsx")
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx", initialfile=default,
            filetypes=[("Excel workbook", "*.xlsx")])
        if not path:
            return
        try:
            export_financial_model(data, path)
        except Exception:
            messagebox.showerror("Financial model export failed",
                                 traceback.format_exc(limit=3))
            return
        self.status_var.set(f"Saved financial model: {path}")

    def fill_workbook(self):
        if self.data is None or self.busy:
            return
        default = (f"{self.data.ticker}_forensic_model_"
                   f"{self.data.generated.isoformat()}.xlsx")
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx", initialfile=default,
            filetypes=[("Excel workbook", "*.xlsx")])
        if not path:
            return
        try:
            report = fill_workbook(self.data, path, res=self.valuation_res,
                                   verdict=self.verdict)
        except Exception:
            messagebox.showerror("Workbook export failed",
                                 traceback.format_exc(limit=3))
            return
        notes = Path(path).with_suffix(".analyst_cells.txt")
        with open(notes, "w", encoding="utf-8") as fh:
            if report.notes:
                fh.write("Data-quality notes:\n")
                for n in report.notes:
                    fh.write(f"  ! {n}\n")
                fh.write("\n")
            fh.write("Blue cells left for the analyst (judgment stays with "
                     "you) — suggested sources:\n\n")
            for sheet, cells, label, source in report.analyst_cells:
                fh.write(f"{sheet}!{cells:<8} {label}\n    -> {source}\n\n")
        self.status_var.set(
            f"Filled {report.filled} blue cells -> {path} "
            f"(analyst to-do: {notes.name})")

    def _set_busy(self, busy: bool, status: str):
        self.busy = busy
        state = tk.DISABLED if busy else tk.NORMAL
        self.analyze_btn.configure(state=state)
        self.compare_btn.configure(state=state)
        buttons = (self.save_btn, self.csv_btn, self.value_btn, self.inputs_btn,
                   self.xlsx_btn, self.html_btn)
        if busy:
            for b in buttons:
                b.configure(state=tk.DISABLED)
        elif self.data is not None:
            for b in buttons:
                b.configure(state=tk.NORMAL)
        self.status_var.set(status)


# Per-method case fields: (attribute, label, unit). unit "%" fields are entered
# in percent (9 = 9%, 160 = 160%); "$" fields are plain dollars.
_METHOD_FIELDS = {
    "dcf": [("g0", "Stage-1 growth g₀", "%"), ("g_term", "Terminal growth g", "%")],
    "ri": [("roe", "Sustainable ROE", "%"), ("g0", "Book growth g₀", "%"),
           ("g_term", "Terminal growth g", "%")],
    "affo": [("affo_ps", "AFFO / share", "$"), ("target_yield", "Target AFFO yield", "%")],
    "manual": [("fv_ps", "FV / share", "$")],
}
_METHOD_HELP = {
    "dcf": "FCFF 2-stage DCF, 10-year linear fade. WACC and the g₀ cases are "
           "pre-filled (auto WACC build; analyst consensus growth: Bear ← low, "
           "Base ← average, Bull ← high) — every value is editable.",
    "ri": "Residual income at r_e (pre-filled from the automated build). BV₀ "
          "defaults to latest reported equity; enter each case's sustainable "
          "ROE and book-growth path.",
    "affo": "REIT AFFO-yield cross-check. AFFO per share and target yield are "
            "analyst-supplied (the FFO→AFFO bridge isn't in XBRL).",
    "manual": "SOTP / external model: enter the FV per share you computed "
              "elsewhere; the app returns the margin of safety.",
}


def _parse_field(raw: str, is_pct: bool) -> Optional[float]:
    """Percent fields are entered in percent units (9 → 0.09, 160 → 1.6); a
    trailing % is tolerated. Dollar/count fields are plain floats."""
    raw = raw.strip().rstrip("%").strip()
    if not raw:
        return None
    v = float(raw)
    if not math.isfinite(v):
        raise ValueError("value must be finite")
    return v / 100.0 if is_pct else v


class _ValuationDialog(tk.Toplevel):
    """Modal: pick a method, enter Bear/Base/Bull assumptions, render pages 4–5."""

    def __init__(self, parent, data: DashboardData, on_done):
        super().__init__(parent)
        self.data = data
        self.on_done = on_done
        self.title("Intrinsic value — Bear / Base / Bull")
        self.transient(parent)
        self.resizable(False, False)
        self.configure(background=P.PAGE)
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

        pre = (f"Pre-selected for the {data.track.title()} track "
               f"(SIC {data.sic_code or '—'}); override if the economic "
               "engine differs.")
        seg = getattr(data, "segments", None)
        if seg is not None and getattr(seg, "n_segments", 0) >= 2:
            ax = seg.axes()[0]
            pre += (f" {seg.n_segments} segments as filed (by {ax}) — SOTP "
                    "candidate; segment values are in the Financial model "
                    "export and the Phase-2 workbook block.")
        ttk.Label(top, style="Secondary.TLabel", text=pre,
                  wraplength=560, justify="left").grid(
            row=1, column=0, columnspan=4, sticky="w", padx=10)

        self.help_lbl = ttk.Label(top, style="Secondary.TLabel", wraplength=560,
                                  justify="left")
        self.help_lbl.grid(row=2, column=0, columnspan=4, sticky="w", **pad)

        self.rate_frame = ttk.Frame(top)
        self.rate_frame.grid(row=3, column=0, columnspan=4, sticky="w", padx=6)
        self.wacc_lbl = ttk.Label(self.rate_frame, text="WACC (%):")
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

        self.estimates_lbl = ttk.Label(top, style="Secondary.TLabel",
                                       wraplength=560, justify="left")
        self.estimates_lbl.grid(row=5, column=0, columnspan=4, sticky="w", padx=10)

        # Phase-5 verdict inputs (§5.3): rating is judgment; the app only
        # checks it for coherence against the MoS (Control!B67 mechanics).
        verdict_frame = ttk.Frame(top)
        verdict_frame.grid(row=6, column=0, columnspan=4, sticky="w", padx=6,
                           pady=(6, 0))
        ttk.Label(verdict_frame, text="Rating (§5.3):").pack(side=tk.LEFT, padx=(4, 4))
        self.rating_var = tk.StringVar(value=data.rating)
        ttk.Combobox(verdict_frame, state="readonly", width=11,
                     textvariable=self.rating_var,
                     values=list(RATINGS)).pack(side=tk.LEFT)
        ttk.Label(verdict_frame, text="Named optionality (§4.D, if any):").pack(
            side=tk.LEFT, padx=(14, 4))
        self.optionality_var = tk.StringVar(value=data.optionality)
        ttk.Entry(verdict_frame, textvariable=self.optionality_var, width=34).pack(
            side=tk.LEFT)

        ttk.Label(top, style="Muted.TLabel",
                  text="Percent fields (%) are entered in percent: 9 = 9%, 160 = 160%. "
                       "Dollar fields ($) are plain amounts.").grid(
            row=7, column=0, columnspan=4, sticky="w", padx=10, pady=(2, 0))

        btns = ttk.Frame(top)
        btns.grid(row=8, column=0, columnspan=4, sticky="e", pady=(10, 0))
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
        self.wacc_var.set("")
        self.base_var.set("")
        build = getattr(self.data, "wacc_build", None)
        if build is not None and method in ("dcf", "ri"):
            rate = build.wacc if method == "dcf" else build.r_e
            if rate is not None:
                self.wacc_var.set(f"{rate * 100:.2f}")
        self.help_lbl.configure(text=_METHOD_HELP[method])
        needs_rate = method in ("dcf", "ri")
        for child in self.rate_frame.winfo_children():
            child.configure(state=tk.NORMAL if needs_rate else tk.DISABLED)
        self.exsbc_chk.configure(state=tk.NORMAL if method == "dcf" else tk.DISABLED)
        self.wacc_lbl.configure(
            text="WACC (%, auto-built):" if method == "dcf" else "r_e (%, auto-built):")
        self.base_lbl.configure(
            text="Base FCFF $ (optional):" if method == "dcf" else "BV₀ $ (optional):")

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

        # Analyst-consensus prefill (dcf): Bear <- low, Base <- avg, Bull <- high
        est = self.data.analyst_estimates
        if method == "dcf" and est:
            fills = (("Bear", est.get("g_low")), ("Base", est.get("g_avg")),
                     ("Bull", est.get("g_high")))
            for case, g in fills:
                if g is not None:
                    self.cell_vars[(case, "g0")].set(f"{g * 100:.1f}")
                self.cell_vars[(case, "g_term")].set("2.0")
            n = est.get("n_analysts")
            self.estimates_lbl.configure(
                text=f"g₀ pre-filled from analyst consensus revenue growth "
                     f"({est['source']}, {est['period']}"
                     + (f", {n} analysts" if n else "") +
                     "); terminal g pre-filled at the 2.0% house default. Edit freely.")
        elif method == "dcf":
            self.estimates_lbl.configure(
                text="No analyst estimates available for this ticker — enter "
                     "your own growth cases.")
        else:
            self.estimates_lbl.configure(text="")

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
            if method in ("dcf", "ri"):
                rate = _parse_field(self.wacc_var.get(), True)
                base = _parse_field(self.base_var.get(), False)
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
            self.data.rating = self.rating_var.get()
            self.data.optionality = self.optionality_var.get().strip()
            verdict = build_verdict(self.data, inputs, res,
                                    rating=self.data.rating,
                                    optionality=self.data.optionality)
            viewport = self.master.winfo_width() or 1160
            dpi = max(70, min(SCREEN_DPI, int(viewport / FIG_W)))
            fig = render_valuation(self.data, res, dpi=dpi)
            verdict_fig = render_verdict(self.data, res, verdict, dpi=dpi)
            self.on_done(fig, res, verdict_fig, verdict)
        except Exception:
            messagebox.showerror("Could not render the valuation page",
                                 traceback.format_exc(limit=3), parent=self)
            return
        self.destroy()


class _AnalystInputsDialog(tk.Toplevel):
    """Judgment inputs the app can't automate: thesis (§2.4), terminal risk
    (§2.3, anchors the Phase-5 rating), and adjusted NI for the fluff filter
    (§3.1). All optional; blank clears."""

    def __init__(self, parent, data: DashboardData, on_done):
        super().__init__(parent)
        self.data = data
        self.on_done = on_done
        self.title("Analyst inputs — thesis, terminal risk, fluff filter")
        self.transient(parent)
        self.resizable(False, False)
        self.configure(background=P.PAGE)
        top = ttk.Frame(self, padding=(12, 12))
        top.pack(fill=tk.BOTH, expand=True)

        gaap = None
        for v in reversed(data.net_income):
            if v is not None:
                gaap = v
                break
        hint = f" (GAAP NI for reference: {gaap:,.0f})" if gaap is not None else ""
        ttk.Label(top, text=f"Adjusted (non-GAAP) net income, latest FY, $ — "
                            f"from the earnings release{hint}:").grid(
            row=0, column=0, sticky="w", pady=(0, 2))
        self.adj_var = tk.StringVar(
            value="" if data.adjusted_ni is None else f"{data.adjusted_ni:.0f}")
        ttk.Entry(top, textvariable=self.adj_var, width=24).grid(
            row=1, column=0, sticky="w", pady=(0, 10))

        ttk.Label(top, text="Investment thesis (§2.4, 3–4 sentences):").grid(
            row=2, column=0, sticky="w", pady=(0, 2))
        self.thesis_txt = tk.Text(top, width=78, height=4, wrap="word",
                                  background="#ffffff", foreground=P.INK_PRIMARY,
                                  insertbackground=P.INK_PRIMARY,
                                  highlightthickness=1,
                                  highlightbackground=P.BASELINE,
                                  highlightcolor=P.GUI_ACCENT, relief="flat")
        self.thesis_txt.grid(row=3, column=0, sticky="w", pady=(0, 10))
        self.thesis_txt.insert("1.0", data.thesis)

        ttk.Label(top, text="Terminal risk (§2.3, cite 10-K Item 1A — anchors "
                            "the Phase-5 rating):").grid(
            row=4, column=0, sticky="w", pady=(0, 2))
        self.risk_txt = tk.Text(top, width=78, height=3, wrap="word",
                                background="#ffffff", foreground=P.INK_PRIMARY,
                                insertbackground=P.INK_PRIMARY,
                                highlightthickness=1,
                                highlightbackground=P.BASELINE,
                                highlightcolor=P.GUI_ACCENT, relief="flat")
        self.risk_txt.grid(row=5, column=0, sticky="w", pady=(0, 10))
        self.risk_txt.insert("1.0", data.terminal_risk)

        ttk.Label(top, text="Non-operating investments, $ (equity bridge, "
                            "Phase1_Anchor!B19 — equity stakes at fair value):").grid(
            row=6, column=0, sticky="w", pady=(0, 2))
        self.nonop_var = tk.StringVar(
            value="" if data.non_op_investments is None
            else f"{data.non_op_investments:.0f}")
        ttk.Entry(top, textvariable=self.nonop_var, width=24).grid(
            row=7, column=0, sticky="w", pady=(0, 10))

        ttk.Label(top, text="SBC override, $/yr (comp note — for a dead "
                            "tagged series or cash-settled LTRP-style "
                            "compensation; drives the Track B ex-SBC basis):").grid(
            row=8, column=0, sticky="w", pady=(0, 2))
        self.sbc_var = tk.StringVar(
            value="" if data.sbc_override is None
            else f"{data.sbc_override:.0f}")
        ttk.Entry(top, textvariable=self.sbc_var, width=24).grid(
            row=9, column=0, sticky="w", pady=(0, 10))

        btns = ttk.Frame(top)
        btns.grid(row=10, column=0, sticky="e")
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(btns, text="Apply", command=self._apply).pack(
            side=tk.RIGHT, padx=(0, 8))
        self.grab_set()

    def _apply(self):
        raw = self.adj_var.get().strip().replace(",", "")
        try:
            adjusted = float(raw) if raw else None
            if adjusted is not None and not math.isfinite(adjusted):
                raise ValueError("must be finite")
        except ValueError as exc:
            messagebox.showerror("Check the inputs",
                                 f"Adjusted net income: {exc}", parent=self)
            return
        nonop_raw = self.nonop_var.get().strip().replace(",", "")
        try:
            nonop = float(nonop_raw) if nonop_raw else None
            if nonop is not None and not math.isfinite(nonop):
                raise ValueError("must be finite")
        except ValueError as exc:
            messagebox.showerror("Check the inputs",
                                 f"Non-op investments: {exc}", parent=self)
            return
        sbc_raw = self.sbc_var.get().strip().replace(",", "")
        try:
            sbc_over = float(sbc_raw) if sbc_raw else None
            if sbc_over is not None and not math.isfinite(sbc_over):
                raise ValueError("must be finite")
        except ValueError as exc:
            messagebox.showerror("Check the inputs",
                                 f"SBC override: {exc}", parent=self)
            return
        set_adjusted_ni(self.data, adjusted)
        self.data.thesis = self.thesis_txt.get("1.0", "end").strip()
        self.data.terminal_risk = self.risk_txt.get("1.0", "end").strip()
        self.data.non_op_investments = nonop
        self.data.sbc_override = sbc_over
        try:
            self.on_done()
        except Exception:
            messagebox.showerror("Could not re-render",
                                 traceback.format_exc(limit=3), parent=self)
            return
        self.destroy()


def run_gui():
    root = tk.Tk()
    apply_brand_theme(root)  # house colour scheme on every widget
    App(root)
    root.mainloop()
