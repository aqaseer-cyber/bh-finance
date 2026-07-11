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
import os
import queue
import subprocess
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
from .anchors import (
    anchor_readout, build_growth_anchors, capex_peak_flag, normalized_base,
)
from .cache import Cache
from .dashboard import (
    FIG_W, render_dashboard, render_health_report, render_unit_economics,
    render_valuation, render_verdict,
)
from .edgar import EdgarError
from .explore import (
    PRICE_MODES, RATIO_MODES, REVENUE_MODES, price_card, ratio_card,
    revenue_card,
)
from .export import export_pdf
from .model_export import export_financial_model
from .compare import MAX_TICKERS, build_compare_html
from .ledger import Ledger
from .metrics import (
    TRACKS, DashboardData, apply_track, compute_altman, fmt_money,
    set_adjusted_ni,
)
from .pipeline import build_dashboard_data
from .valuation import (
    CASE_NAMES, METHODS, CaseInputs, ValuationError, ValuationInputs,
    build_valuation, suggest_method,
)
from .verdict import RATINGS, build_verdict
from .workbook import fill_workbook

SCREEN_DPI = 100  # fallback dpi cap for on-screen rasters (used only when
#                   the display DPI is unknown); the PDF export is vector
YEAR_CHOICES = ("3", "5", "7", "10")
PAGES = ("Dashboard", "Unit economics", "Health checks", "Valuation", "Verdict")
REPO_URL = "https://github.com/aqaseer-cyber/bh-finance"


def _open_folder(path) -> None:
    """Open a folder in the OS file browser (best-effort, never raises)."""
    try:
        p = str(path)
        if sys.platform == "win32":
            os.startfile(p)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", p])
        else:
            subprocess.Popen(["xdg-open", p])
    except Exception:
        pass


# Watchlist column → raw ledger-row value (FIX-12f click-to-sort). Sorting
# reads the raw values, never the formatted display strings.
_WATCH_SORT_KEYS = {
    "ticker": lambda r: r.get("ticker") or "",
    "rating": lambda r: r.get("rating") or "",
    "fv": lambda r: r.get("fv_avg"),
    "mos": lambda r: r.get("mos"),
    "smos": lambda r: r.get("stressed_mos"),
    "price": lambda r: r.get("price"),
    "asof": lambda r: r.get("price_date") or "",
    "age": lambda r: r.get("age_days"),
    "gate": lambda r: r.get("coherence") or "",
    "trig": lambda r: r.get("open_triggers") or 0,
}


def watchlist_sort(rows, col, reverse=False):
    """Sort ledger rows by a column, numeric-aware; rows missing the value
    sort last in either direction. Pure — unit-tested without Tk."""
    key = _WATCH_SORT_KEYS.get(col)
    if key is None:
        return list(rows)

    def norm(r):
        v = key(r)
        return v.upper() if isinstance(v, str) else v

    present = [r for r in rows if key(r) is not None]
    missing = [r for r in rows if key(r) is None]
    return sorted(present, key=norm, reverse=reverse) + missing


def watchlist_tags(rec) -> tuple:
    """Row tags for a ledger record: MoS sign colour, then `stale` last so
    its red keeps precedence. Pure — unit-tested without Tk."""
    tags = []
    if rec.get("mos") is not None:
        tags.append("neg" if rec["mos"] < 0 else "pos")
    if rec.get("stale"):
        tags.append("stale")
    return tuple(tags)


def _enable_windows_dpi_awareness() -> None:
    """Per-monitor DPI awareness — must run BEFORE tk.Tk() is constructed,
    or Windows bitmap-stretches the whole app at 125–150% display scaling.
    No-op off Windows."""
    if sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _apply_tk_scaling(root) -> float:
    """Point-correct Tk scaling from the real display DPI. Returns dpi."""
    try:
        dpi = root.winfo_fpixels("1i")
        root.tk.call("tk", "scaling", dpi / 72.0)
        return float(dpi)
    except tk.TclError:
        return 96.0


def _display_dpi_of(widget) -> float:
    """Physical display DPI for any widget, 96 when unknown."""
    try:
        return float(widget.winfo_fpixels("1i"))
    except Exception:
        return 96.0


def _should_rerender(old_dpi, new_dpi) -> bool:
    """Re-render only on a meaningful density change (≥ 6 dpi) — resizing
    by a few pixels must not burn a full page re-render (FIX-12b)."""
    return old_dpi is None or abs(new_dpi - old_dpi) >= 6


def _set_app_icon(root) -> None:
    """Window/taskbar icon from the bundled assets (best-effort)."""
    from .workbook import asset_path
    try:
        png = asset_path("app_icon.png")
        if png.is_file():
            root.iconphoto(True, tk.PhotoImage(file=str(png)))
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            ico = asset_path("app_icon.ico")
            if ico.is_file():
                root.iconbitmap(default=str(ico))
        except Exception:
            pass


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
        self._win = self.canvas.create_window((0, 0), window=self.inner,
                                              anchor="nw")
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._recenter)
        self.fig_canvas: Optional[FigureCanvasTkAgg] = None

    def _recenter(self, _e=None):
        """Center the page horizontally when the viewport is wider."""
        if self.fig_canvas is None:
            return
        fw = self.fig_canvas.get_tk_widget().winfo_reqwidth()
        x = max(0, (self.canvas.winfo_width() - fw) // 2)
        self.canvas.coords(self._win, x, 0)

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
        self._recenter()


class _SandboxCard(ttk.Frame):
    """FIX-15c: native DCF sandbox — a thin Tk skin over the PRODUCTION
    functions (`dcf_fcff` via `sandbox_compute`, the last valuation's
    bridge, `reverse_dcf_implied_g`). Deliberately no new math. Visible
    once a DCF valuation exists; other methods get a muted note (banks /
    REITs mirror the old HTML behavior). The app's valuation page and
    exports stay the audited record."""

    _SLIDERS = (  # (attr, label, lo %, hi %)
        ("wacc", "WACC", 5.0, 15.0),
        ("g0", "Stage-1 g₀", -5.0, 25.0),
        ("gt", "Terminal g", 0.0, config.GDP_CAP * 100),
    )

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._job = None
        head = ttk.Frame(self)
        head.pack(fill=tk.X, padx=10, pady=(16, 2), anchor="w")
        ttk.Label(head, text="DCF sandbox (§4.A)",
                  font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        self.note = ttk.Label(self, style="Secondary.TLabel", justify="left",
                              text="Run Intrinsic value… (DCF) to enable "
                                   "the sandbox.")
        self.note.pack(fill=tk.X, padx=12, anchor="w")
        self.body = ttk.Frame(self)

        row = ttk.Frame(self.body)
        row.pack(fill=tk.X, padx=12, pady=(4, 2), anchor="w")
        ttk.Label(row, text="Base FCFF ($mm, as-reported):").pack(side=tk.LEFT)
        self.base_var = tk.StringVar()
        base_entry = ttk.Entry(row, textvariable=self.base_var, width=12)
        base_entry.pack(side=tk.LEFT, padx=(6, 14))
        base_entry.bind("<KeyRelease>", lambda _e: self._debounced())
        self.exsbc_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="ex-SBC base (house §2b)",
                        variable=self.exsbc_var,
                        command=self._debounced).pack(side=tk.LEFT)
        ttk.Label(row, text="Reset to case:").pack(side=tk.LEFT, padx=(16, 4))
        self.case_var = tk.StringVar(value="Base")
        case_box = ttk.Combobox(row, state="readonly", width=6,
                                textvariable=self.case_var,
                                values=list(CASE_NAMES))
        case_box.pack(side=tk.LEFT)
        case_box.bind("<<ComboboxSelected>>", lambda _e: self._reset_case())

        self._scale_vars, self._scale_labels = {}, {}
        for attr, label, lo, hi in self._SLIDERS:
            srow = ttk.Frame(self.body)
            srow.pack(fill=tk.X, padx=12, pady=1, anchor="w")
            ttk.Label(srow, text=label, width=11).pack(side=tk.LEFT)
            var = tk.DoubleVar(value=lo)
            self._scale_vars[attr] = var
            ttk.Scale(srow, from_=lo, to=hi, variable=var, length=280,
                      command=lambda _v, a=attr: self._on_slide(a)).pack(
                side=tk.LEFT, padx=(4, 8))
            live = ttk.Label(srow, width=8)
            live.pack(side=tk.LEFT)
            self._scale_labels[attr] = live

        out = ttk.Frame(self.body)
        out.pack(fill=tk.X, padx=12, pady=(6, 10), anchor="w")
        self._outputs = {}
        for col, (key, label) in enumerate((
                ("fv_ps", "FV / share"), ("mos", "MoS vs P₀"),
                ("tv_share", "TV % of EV"), ("implied_g", "implied g (Track B)"))):
            ttk.Label(out, text=label, style="Muted.TLabel").grid(
                row=0, column=col, sticky="w", padx=(0, 22))
            val = ttk.Label(out, text="–", font=("Segoe UI", 11, "bold"))
            val.grid(row=1, column=col, sticky="w", padx=(0, 22))
            self._outputs[key] = val

    # sliders update their live label instantly; the compute is debounced
    # 100 ms so drags stay smooth (FIX-15c)
    def _on_slide(self, attr):
        v = self._scale_vars[attr].get()
        self._scale_labels[attr].configure(text=f"{v:.1f}%")
        self._debounced()

    def _debounced(self):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(100, self._recompute)

    def _reset_case(self):
        res = self.app.valuation_res
        inputs = getattr(res, "_inputs", None)
        if res is None or inputs is None:
            return
        case = inputs.cases.get(self.case_var.get())
        if case is None or case.g0 is None:
            return
        self._scale_vars["g0"].set(case.g0 * 100)
        self._scale_vars["gt"].set(case.g_term * 100)
        if res.discount_rate:
            self._scale_vars["wacc"].set(res.discount_rate * 100)
        self._seed_base(res)
        for attr in self._scale_vars:
            self._scale_labels[attr].configure(
                text=f"{self._scale_vars[attr].get():.1f}%")
        self._recompute()

    def _seed_base(self, res):
        """Entry always holds the AS-REPORTED base: un-subtract SBC when
        the last valuation ran ex-SBC, and mirror its checkbox — the
        sandbox then reproduces that valuation exactly."""
        base = res.base_value
        if base is None:
            return
        inputs = getattr(res, "_inputs", None)
        ex = bool(inputs is not None and inputs.ex_sbc)
        if ex:
            from .valuation import effective_sbc
            base += effective_sbc(self.app.data) or 0.0
        self.exsbc_var.set(ex)
        self.base_var.set(f"{base / 1e6:.0f}")

    def refresh(self):
        res = self.app.valuation_res
        if res is None:
            self.body.pack_forget()
            self.note.configure(text="Run Intrinsic value… (DCF) to enable "
                                     "the sandbox.")
            self.note.pack(fill=tk.X, padx=12, anchor="w")
            return
        if res.method != "dcf":
            self.body.pack_forget()
            self.note.configure(
                text=f"Sandbox applies to the DCF method — the last "
                     f"valuation used '{res.method}' (banks/REITs value "
                     "through ROE/AFFO, not an FCFF fade).")
            self.note.pack(fill=tk.X, padx=12, anchor="w")
            return
        self.note.pack_forget()
        self.body.pack(fill=tk.X, anchor="w")
        self.case_var.set("Base")
        self._reset_case()

    def _recompute(self):
        self._job = None
        d, res = self.app.data, self.app.valuation_res
        if d is None or res is None:
            return
        from .valuation import effective_sbc
        from .explore import sandbox_compute
        try:
            base = float(self.base_var.get().replace(",", "")) * 1e6
        except ValueError:
            self._show_error("n/a — base must be a number ($mm)")
            return
        bridge = res.bridge if res.bridge is not None else (res.net_debt or 0.0)
        out = sandbox_compute(
            base, self._scale_vars["wacc"].get() / 100,
            self._scale_vars["g0"].get() / 100,
            self._scale_vars["gt"].get() / 100,
            bridge, res.shares, effective_sbc(d) or 0.0,
            self.exsbc_var.get(), price=d.last_close)
        if out["error"]:
            self._show_error(out["error"])
            return
        neg = P.NEGATIVE
        ink = P.INK_PRIMARY
        self._outputs["fv_ps"].configure(
            text=f"${out['fv_ps']:,.2f}", foreground=ink)
        mos = out["mos"]
        self._outputs["mos"].configure(
            text=f"{mos * 100:+.1f}%" if mos is not None else "–",
            foreground=neg if mos is not None and mos < 0 else ink)
        self._outputs["tv_share"].configure(
            text=f"{out['tv_share'] * 100:.0f}%", foreground=ink)
        ig = out["implied_g"]
        self._outputs["implied_g"].configure(
            text=f"{ig * 100:.1f}%" if ig is not None else "–",
            foreground=ink)

    def _show_error(self, msg):
        self._outputs["fv_ps"].configure(text=msg, foreground=P.NEGATIVE)
        for key in ("mos", "tv_share", "implied_g"):
            self._outputs[key].configure(text="–", foreground=P.INK_PRIMARY)


class _ExploreTab(ttk.Frame):
    """FIX-15b: a scrollable column of live chart cards, screen-only
    (the report/PDF pipeline never renders these figures). Each card is a
    title + mode combobox over its own small canvas; a mode change redraws
    THAT card only. Figures are plt-free (`Figure()` directly), so
    destroying the old Tk canvas releases them — no figure leaks."""

    _CARDS = (("Share price & drawdown", PRICE_MODES, price_card),
              ("Valuation ratios (TTM)", RATIO_MODES, ratio_card),
              ("Revenue & margins", REVENUE_MODES, revenue_card))

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.canvas = tk.Canvas(self, background=P.PAGE, highlightthickness=0)
        vbar = ttk.Scrollbar(self, orient=tk.VERTICAL,
                             command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vbar.set)
        vbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.inner = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner,
                                              anchor="nw")
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self._cards = []
        for title, modes, builder in self._CARDS:
            head = ttk.Frame(self.inner)
            head.pack(fill=tk.X, padx=10, pady=(12, 2), anchor="w")
            ttk.Label(head, text=title,
                      font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
            var = tk.StringVar(value=modes[0])
            box = ttk.Combobox(head, state="readonly", width=18,
                               textvariable=var, values=list(modes))
            box.pack(side=tk.LEFT, padx=(12, 0))
            holder = ttk.Frame(self.inner)
            holder.pack(fill=tk.X, padx=10, anchor="w")
            card = {"var": var, "builder": builder, "holder": holder,
                    "canvas": None}
            box.bind("<<ComboboxSelected>>",
                     lambda _e, c=card: self._redraw(c))
            self._cards.append(card)
        # FIX-15c: the fourth card is controls, not a figure
        self.sandbox = _SandboxCard(self.inner, app)
        self.sandbox.pack(fill=tk.X, anchor="w")

    def _card_geometry(self):
        dpi = int(min(getattr(self.app, "_display_dpi", 96) or 96, 180))
        width_px = (self.canvas.winfo_width()
                    or self.app.notebook.winfo_width() or 1000)
        return dpi, max(560, width_px - 44) / dpi

    def _redraw(self, card):
        d = self.app.data
        if d is None:
            return
        dpi, width_in = self._card_geometry()
        fig = card["builder"](d, card["var"].get(), dpi=dpi,
                              width_in=width_in)
        if card["canvas"] is not None:
            card["canvas"].get_tk_widget().destroy()
        card["canvas"] = FigureCanvasTkAgg(fig, master=card["holder"])
        card["canvas"].draw()
        card["canvas"].get_tk_widget().pack(anchor="w")

    def refresh(self):
        """Re-render every card (fresh data or a DPI/viewport change)."""
        for card in self._cards:
            self._redraw(card)
        self.sandbox.refresh()


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self._display_dpi = _apply_tk_scaling(root)  # before any geometry
        _set_app_icon(root)
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
        self.years_var = tk.StringVar(value=str(config.GUI_DEFAULT_YEARS))
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
        ui_scale = self._display_dpi / 96.0  # wraplengths are pixel counts
        self._status_label = ttk.Label(
            side, textvariable=self.status_var, style="Side.TLabel",
            wraplength=int(160 * ui_scale), justify="left")
        self._status_label.pack(side=tk.BOTTOM, anchor="w", pady=(12, 0))
        # FIX-12g busy affordance — packed only while a fetch runs
        self.progress = ttk.Progressbar(side, mode="indeterminate", length=160)
        self.cancel_btn = ttk.Button(side, text="Cancel", style="Side.TButton",
                                     command=self._cancel_run)
        self._cancel_event: Optional[threading.Event] = None

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
        # FIX-15b: Explore cards (screen-only, never in the PDF)
        self.explore_tab = _ExploreTab(self.notebook, self)
        self.notebook.add(self.explore_tab, text="Explore", state=tk.DISABLED)
        self.refresh_watchlist()

        root.bind_all("<MouseWheel>", self._on_mousewheel)      # Windows/macOS
        root.bind_all("<Button-4>", self._on_mousewheel_linux)  # X11
        root.bind_all("<Button-5>", self._on_mousewheel_linux)
        # FIX-12b: debounced native re-render when the viewport density
        # changes (maximize/shrink) — pages stay sharp at every size
        self._resize_job = None
        self._last_render_dpi = None
        self.notebook.bind("<Configure>", self._on_viewport_resize)
        self._build_menu(root)  # FIX-12e: File / Tools / Help
        self.root.after(400, self._maybe_prompt_ua)
        self.root.after(120, self._poll_queue)

    # ------------------------------------------------- menu bar (FIX-12e)

    def _build_menu(self, root):
        menubar = tk.Menu(root)
        m_file = tk.Menu(menubar, tearoff=0)
        m_file.add_command(label="Save PDF (A4)…", command=self.save_pdf)
        m_file.add_command(label="Financial model…", command=self.export_model)
        m_file.add_command(label="Fill workbook…", command=self.fill_workbook)
        m_file.add_separator()
        m_file.add_command(label="Exit", command=root.destroy)
        m_tools = tk.Menu(menubar, tearoff=0)
        m_tools.add_command(label="Compare…", command=self.compare)
        m_tools.add_separator()
        m_tools.add_command(label="Settings…", command=self.open_settings)
        m_help = tk.Menu(menubar, tearoff=0)
        m_help.add_command(label="About Forensic Stock Viz",
                           command=self.show_about)
        m_help.add_separator()
        m_help.add_command(label="Open cache folder",
                           command=lambda: _open_folder(config.cache_dir()))
        m_help.add_command(
            label="Open settings folder",
            command=lambda: _open_folder(config.settings_path().parent))
        menubar.add_cascade(label="File", menu=m_file)
        menubar.add_cascade(label="Tools", menu=m_tools)
        menubar.add_cascade(label="Help", menu=m_help)
        root.config(menu=menubar)
        self._menu_file, self._menu_tools = m_file, m_tools
        self._sync_menu_state()

    def _sync_menu_state(self):
        """Menu items mirror the sidebar buttons' enabled state."""
        if not hasattr(self, "_menu_file"):
            return
        data_state = (tk.NORMAL if (self.data is not None and not self.busy)
                      else tk.DISABLED)
        any_state = tk.DISABLED if self.busy else tk.NORMAL
        for label in ("Save PDF (A4)…", "Financial model…", "Fill workbook…"):
            self._menu_file.entryconfig(label, state=data_state)
        self._menu_tools.entryconfig("Compare…", state=any_state)

    def _maybe_prompt_ua(self):
        """One-time offer to open Settings when the SEC UA is a placeholder
        (persisted flag — the app never nags twice)."""
        if not config.UA_IS_PLACEHOLDER:
            return
        s = config.load_user_settings()
        if s.get("ua_prompted"):
            return
        s["ua_prompted"] = True
        try:
            config.save_user_settings(s)
        except Exception:
            pass  # a read-only profile must not break startup
        if messagebox.askyesno(
                "SEC User-Agent",
                "The SEC requires an identifying User-Agent (name and email) "
                "on EDGAR requests.\n\nOpen Settings to configure it now?",
                parent=self.root):
            self.open_settings()

    def open_settings(self):
        _SettingsDialog(self.root, on_saved=self._on_settings_saved)

    def _on_settings_saved(self):
        msg = "Settings saved."
        if not config.UA_IS_PLACEHOLDER:
            msg += "  SEC User-Agent configured."
        else:
            msg += f"  {config.UA_WARNING}"
        self.status_var.set(msg)

    def show_about(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("About")
        dlg.transient(self.root)
        dlg.resizable(False, False)
        dlg.configure(background=P.PAGE)
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        frame = ttk.Frame(dlg, padding=(18, 14))
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text=f"Forensic Stock Viz {config.APP_VERSION}",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(frame, wraplength=380, justify="left", text=(
            "Five-phase forensic valuation reports from SEC EDGAR XBRL — "
            "fundamentals, unit economics, health checks, intrinsic value "
            "and the Phase-5 verdict. Not investment advice.")).pack(
            anchor="w", pady=(6, 8))
        link = ttk.Label(frame, text=REPO_URL, foreground=P.INK_PRIMARY,
                         cursor="hand2")
        link.pack(anchor="w")
        link.bind("<Button-1>", lambda _e: webbrowser.open(REPO_URL))
        strip = tk.Canvas(frame, width=6 * 34, height=18,
                          background=P.PAGE, highlightthickness=0)
        strip.pack(anchor="w", pady=(10, 4))
        for i, c in enumerate(P.SERIES):
            strip.create_rectangle(i * 34, 0, i * 34 + 28, 18,
                                   fill=c, outline="")
        ttk.Button(frame, text="Close", command=dlg.destroy).pack(
            anchor="e", pady=(10, 0))

    # -------------------------------------------------------- resize hook

    def _on_viewport_resize(self, _e):
        if self._resize_job:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(300, self._maybe_rerender)

    def _maybe_rerender(self):
        self._resize_job = None
        if self.busy or self.data is None:
            return
        dpi = self._screen_dpi()
        if not _should_rerender(self._last_render_dpi, dpi):
            return
        self._rerender_all(dpi)

    def _rerender_all(self, dpi: int):
        current = self.notebook.select()
        self.figs["Dashboard"] = render_dashboard(self.data, dpi=dpi)
        self.figs["Unit economics"] = render_unit_economics(self.data, dpi=dpi)
        self.figs["Health checks"] = render_health_report(self.data, dpi=dpi)
        if self.valuation_res is not None:
            self.figs["Valuation"] = render_valuation(
                self.data, self.valuation_res, dpi=dpi)
            if self.verdict is not None:
                self.figs["Verdict"] = render_verdict(
                    self.data, self.valuation_res, self.verdict, dpi=dpi,
                    open_triggers=self._open_trigger_texts())
        self._refresh_tabs()
        self.explore_tab.refresh()  # FIX-15b: cards re-render at the new DPI
        if current:
            try:
                self.notebook.select(current)
            except tk.TclError:
                pass
        self._last_render_dpi = dpi

    # ------------------------------------------------------------ watchlist

    def _build_watchlist_tab(self):
        frame = ttk.Frame(self.notebook, padding=(8, 8))
        self.notebook.add(frame, text="Watchlist")
        cols = ("ticker", "rating", "fv", "mos", "smos", "price", "asof",
                "age", "gate", "trig")
        heads = ("Ticker", "Rating", "FV avg", "MoS", "Stressed", "P₀",
                 "As of", "Age (d)", "Gate", "Open trig")
        widths = (70, 80, 80, 70, 70, 70, 90, 60, 230, 70)
        numeric = {"fv", "mos", "smos", "price", "age"}  # right-aligned
        self._watch_sort = (None, False)  # (column, reverse)
        self.tree = ttk.Treeview(frame, columns=cols, show="headings",
                                 selectmode="browse")
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h,
                              command=lambda col=c: self._on_watch_sort(col))
            self.tree.column(c, width=w, anchor="e" if c in numeric else "w")
        self.tree.tag_configure("neg", foreground=P.NEGATIVE)
        self.tree.tag_configure("pos", foreground=P.DELTA_GOOD)
        self.tree.tag_configure("stale", foreground=P.NEGATIVE)  # wins (last)
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
        self.history_btn = ttk.Button(btns, text="History…",
                                      command=self._history_selected)
        if not hasattr(self.ledger, "history"):  # pre-FIX-6 ledger builds
            self.history_btn.configure(state=tk.DISABLED)
        self.history_btn.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(btns, style="Muted.TLabel",
                  text="Verdict ledger (§5.7) — rows log automatically when a "
                       "valuation runs; red = stale (> ~5 trading days, house §8). "
                       "Click a heading to sort; double-click to re-run.").pack(
            side=tk.LEFT, padx=(14, 0))

    def _on_watch_sort(self, col: str):
        prev_col, prev_rev = self._watch_sort
        self._watch_sort = (col, not prev_rev if prev_col == col else False)
        self.refresh_watchlist()

    def refresh_watchlist(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        rows = self.ledger.list_verdicts()
        col, rev = self._watch_sort
        if col:
            rows = watchlist_sort(rows, col, rev)
        for rec in rows:
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
            ), tags=watchlist_tags(rec))

    def _history_selected(self):
        """FIX-12f: read-only viewer over the FIX-6 verdict history."""
        ticker = self._selected_ticker()
        if not ticker or self.busy or not hasattr(self.ledger, "history"):
            return
        try:
            rows = self.ledger.history(ticker)
        except Exception:
            rows = []
        dlg = tk.Toplevel(self.root)
        dlg.title(f"Verdict history — {ticker}"
                  + (" (no rows yet)" if not rows else ""))
        dlg.transient(self.root)
        dlg.configure(background=P.PAGE)
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
        cols = ("recorded", "rating", "fv", "mos", "gate")
        heads = ("Recorded", "Rating", "FV avg", "MoS", "Gate")
        widths = (170, 80, 90, 70, 230)
        tree = ttk.Treeview(dlg, columns=cols, show="headings", height=12)
        for c, h, w in zip(cols, heads, widths):
            tree.heading(c, text=h)
            tree.column(c, width=w, anchor="e" if c in ("fv", "mos") else "w")
        for r in reversed(rows):  # newest first
            tree.insert("", tk.END, values=(
                r.get("recorded_at") or "–", r.get("rating") or "–",
                f"${r['fv_avg']:,.2f}" if r.get("fv_avg") is not None else "–",
                f"{r['mos'] * 100:+.1f}%" if r.get("mos") is not None else "–",
                r.get("coherence") or "–"))
        vsb = ttk.Scrollbar(dlg, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                  padx=(10, 0), pady=10)
        vsb.pack(side=tk.RIGHT, fill=tk.Y, pady=10, padx=(0, 10))

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
        _CompareDialog(self.root, self._start_compare)

    def _start_compare(self, raw: str):
        tickers = [t.strip().upper() for t in raw.replace(";", ",").split(",")
                   if t.strip()][:MAX_TICKERS]
        if len(tickers) < 2:
            messagebox.showinfo("Compare", "Enter at least two tickers.")
            return
        self._cancel_event = threading.Event()
        self._set_busy(True, f"Comparing {', '.join(tickers)}…")
        threading.Thread(target=self._compare_worker,
                         args=(tickers, self._cancel_event),
                         daemon=True).start()

    def _compare_worker(self, tickers, cancel: threading.Event):
        try:
            datas = []
            for t in tickers:
                if cancel.is_set():  # FIX-12g: between-tickers checkpoint
                    self.queue.put(("cancelled", "comparison"))
                    return
                self.queue.put(("status", f"Fetching {t}…"))
                datas.append(build_dashboard_data(
                    t, cache=Cache(),
                    progress=lambda m: None,
                    track="auto", years=int(self.years_var.get()),
                    cancel=cancel))
            rows = {r["ticker"]: r for r in Ledger().list_verdicts()}  # own conn (thread)
            out = Path(tempfile.gettempdir()) / (
                "_vs_".join(tickers) + "_compare.html")
            build_compare_html(datas, str(out), ledger_rows=rows)
            self.queue.put(("compare", str(out)))
        except EdgarError as exc:
            if "cancelled" in str(exc):
                self.queue.put(("cancelled", "comparison"))
            else:
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
        self._cancel_event = threading.Event()
        self._set_busy(True, f"Fetching data for {ticker}…")
        threading.Thread(target=self._worker,
                         args=(ticker, self._cancel_event),
                         daemon=True).start()

    def _cancel_run(self):
        """FIX-12g: cooperative cancel — the worker stops at the next stage
        boundary; nothing is torn down mid-request."""
        if self._cancel_event is not None and not self._cancel_event.is_set():
            self._cancel_event.set()
            self.status_var.set("Cancelling — stopping at the next stage…")

    def _worker(self, ticker: str, cancel: threading.Event):
        try:
            data = build_dashboard_data(
                ticker,
                cache=Cache(),
                progress=lambda msg: self.queue.put(("status", msg)),
                track=self.track_var.get(),
                years=int(self.years_var.get()),
                cancel=cancel,
            )
            self.queue.put(("data", data))
        except EdgarError as exc:
            if "cancelled" in str(exc):
                self.queue.put(("cancelled", ticker))
            else:
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
                elif kind == "cancelled":
                    self._set_busy(False, f"Cancelled — {payload} not built.")
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
        # native-resolution rasters: cap at the physical display DPI (bounded
        # at 180 for memory), not the old fixed 100
        viewport = self.notebook.winfo_width() or 1060
        cap = int(min(getattr(self, "_display_dpi", 96) * 1.0, 180))
        return max(70, min(cap, int((viewport - 30) / FIG_W)))

    def _show(self, data: DashboardData):
        self.status_var.set("Rendering…")
        self.root.update_idletasks()
        dpi = self._screen_dpi()
        self._last_render_dpi = dpi
        self.data = data
        self.figs["Dashboard"] = render_dashboard(data, dpi=dpi)
        self.figs["Unit economics"] = render_unit_economics(data, dpi=dpi)
        self.figs["Health checks"] = render_health_report(data, dpi=dpi)
        self.figs["Valuation"] = None
        self.figs["Verdict"] = None
        self.valuation_res = None
        self.verdict = None
        self._refresh_tabs(select="Dashboard")
        self.explore_tab.refresh()
        self.notebook.tab(self.explore_tab, state=tk.NORMAL)
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
        self._last_render_dpi = dpi
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
        _ValuationDialog(self.root, self.data, self._on_valuation_done,
                         open_triggers=self._open_trigger_texts())

    def _open_trigger_texts(self):
        """Open ledger triggers for the current ticker — the verdict page's
        trigger box (FIX-12d). The ledger never blocks rendering."""
        if self.data is None:
            return None
        try:
            return [t["trigger_text"]
                    for t in self.ledger.open_triggers(self.data.ticker)]
        except Exception:
            return None

    def _on_valuation_done(self, fig, res, verdict_fig, verdict):
        self.figs["Valuation"] = fig
        self.figs["Verdict"] = verdict_fig
        self.valuation_res = res
        self.verdict = verdict
        self._last_render_dpi = self._screen_dpi()
        try:  # §5.7: no verdict leaves the session unlogged
            self.ledger.upsert_verdict(self.data, res=res, verdict=verdict)
            self.refresh_watchlist()
            led = " (ledger updated)"
        except Exception as exc:  # still non-blocking, but visibly so (12g)
            led = f" (ledger update failed: {type(exc).__name__})"
        self._refresh_tabs(select="Valuation")
        self.explore_tab.sandbox.refresh()  # FIX-15c: seed from this valuation
        gate = f" · rating gate: {verdict.coherence}" if verdict is not None else ""
        self.status_var.set(f"Intrinsic value + verdict ready.{led}{gate}")

    def analyst_inputs(self):
        if self.data is None or self.busy:
            return
        _AnalystInputsDialog(self.root, self.data, self._on_analyst_inputs)

    def _on_analyst_inputs(self):
        dpi = self._screen_dpi()
        self._last_render_dpi = dpi
        self.figs["Unit economics"] = render_unit_economics(self.data, dpi=dpi)
        self.figs["Health checks"] = render_health_report(self.data, dpi=dpi)
        self._refresh_tabs(select="Unit economics")
        note = ""
        if self.data.adjustment_burden is not None:
            burden = self.data.adjustment_burden
            flag = " FLAG >20%" if burden > 0.20 else ""
            note = f"  Adjustment burden {burden * 100:.1f}%{flag}."
        self.status_var.set(f"Analyst inputs applied.{note}")

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
                   self.xlsx_btn)
        if busy:
            for b in buttons:
                b.configure(state=tk.DISABLED)
        elif self.data is not None:
            for b in buttons:
                b.configure(state=tk.NORMAL)
        self._sync_menu_state()  # menu mirrors the sidebar (FIX-12e)
        # FIX-12g busy affordance: spinner under the status line + Cancel
        if busy:
            self.progress.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0),
                               before=self._status_label)
            self.progress.start(80)
            self.cancel_btn.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0),
                                 before=self.progress)
        else:
            self.progress.stop()
            self.progress.pack_forget()
            self.cancel_btn.pack_forget()
        self.status_var.set(status)


class _CompareDialog(tk.Toplevel):
    """FIX-12g: branded replacement for simpledialog.askstring — same
    parsing, same worker; Return submits, Escape closes."""

    def __init__(self, parent, on_submit):
        super().__init__(parent)
        self.on_submit = on_submit
        self.title("Compare tickers")
        self.transient(parent)
        self.resizable(False, False)
        self.configure(background=P.PAGE)
        top = ttk.Frame(self, padding=(14, 12))
        top.pack(fill=tk.BOTH, expand=True)
        ttk.Label(top, text=f"Enter 2–{MAX_TICKERS} tickers, "
                            "comma-separated").pack(anchor="w")
        self.var = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.var, width=38)
        entry.pack(anchor="w", pady=(4, 2))
        entry.focus_set()
        ttk.Label(top, foreground=P.INK_MUTED,
                  text="e.g. AAPL, MSFT — side-by-side fundamentals with "
                       "ledger verdicts").pack(anchor="w")
        btns = ttk.Frame(top)
        btns.pack(anchor="e", pady=(10, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(
            side=tk.RIGHT, padx=(6, 0))
        ttk.Button(btns, text="Compare", style="Accent.TButton",
                   command=self._submit).pack(side=tk.RIGHT)
        self.bind("<Return>", lambda _e: self._submit())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()

    def _submit(self):
        raw = self.var.get().strip()
        self.destroy()
        if raw:
            self.on_submit(raw)


class _SettingsDialog(tk.Toplevel):
    """FIX-12e: persisted user settings — SEC User-Agent, house assumptions
    file, default years window. Precedence stays env var > settings.json >
    placeholder; the dialog only fills the gaps env vars leave open."""

    def __init__(self, parent, on_saved=None):
        super().__init__(parent)
        self.on_saved = on_saved
        self.title("Settings")
        self.transient(parent)
        self.resizable(False, False)
        self.configure(background=P.PAGE)
        self.bind("<Escape>", lambda _e: self.destroy())
        s = config.load_user_settings()
        top = ttk.Frame(self, padding=(14, 12))
        top.pack(fill=tk.BOTH, expand=True)

        ttk.Label(top, text="SEC EDGAR User-Agent").grid(
            row=0, column=0, sticky="w")
        saved_ua = str(s.get("sec_user_agent") or "")
        self.ua_var = tk.StringVar(value=saved_ua or (
            "" if config.UA_IS_PLACEHOLDER else config.SEC_USER_AGENT))
        ttk.Entry(top, textvariable=self.ua_var, width=52).grid(
            row=1, column=0, columnspan=3, sticky="we", pady=(2, 0))
        hint = "name email — SEC requires this"
        if os.environ.get("SEC_EDGAR_USER_AGENT"):
            hint += "  (env var SEC_EDGAR_USER_AGENT is set and wins)"
        ttk.Label(top, text=hint, foreground=P.INK_MUTED).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(0, 10))

        ttk.Label(top, text="House assumptions file").grid(
            row=3, column=0, sticky="w")
        self.house_var = tk.StringVar(value=str(s.get("house_file") or ""))
        ttk.Entry(top, textvariable=self.house_var, width=42,
                  state="readonly").grid(row=4, column=0, columnspan=2,
                                         sticky="we", pady=(2, 0))
        ttk.Button(top, text="Browse…", command=self._browse_house).grid(
            row=4, column=2, sticky="e", padx=(6, 0), pady=(2, 0))
        ttk.Label(top, text="takes effect next launch",
                  foreground=P.INK_MUTED).grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(0, 10))

        ttk.Label(top, text="Default years window").grid(
            row=6, column=0, sticky="w")
        self.years_var = tk.StringVar(value=str(config.GUI_DEFAULT_YEARS))
        ttk.Combobox(top, state="readonly", width=5,
                     textvariable=self.years_var,
                     values=list(YEAR_CHOICES)).grid(
            row=7, column=0, sticky="w", pady=(2, 12))

        btns = ttk.Frame(top)
        btns.grid(row=8, column=0, columnspan=3, sticky="e")
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(
            side=tk.RIGHT, padx=(6, 0))
        ttk.Button(btns, text="Save", style="Accent.TButton",
                   command=self._save).pack(side=tk.RIGHT)
        self.grab_set()

    def _browse_house(self):
        path = filedialog.askopenfilename(
            parent=self, title="House assumptions file",
            filetypes=[("TOML", "*.toml"), ("All files", "*.*")])
        if path:
            self.house_var.set(path)

    def _save(self):
        s = config.load_user_settings()
        s["sec_user_agent"] = self.ua_var.get().strip()
        s["house_file"] = self.house_var.get().strip()
        try:
            s["default_years"] = int(self.years_var.get())
        except ValueError:
            pass
        try:
            config.save_user_settings(s)
        except Exception:
            messagebox.showerror("Settings", "Could not write settings.json — "
                                             "check the app-data folder.",
                                 parent=self)
            return
        config.apply_user_settings(s)
        if self.on_saved:
            self.on_saved()
        self.destroy()


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
           "pre-filled (auto WACC build; growth-anchor ladder: Bull ← "
           "consensus, Base ← min anchor, Bear ← ½ Base) — every value is "
           "editable.",
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

    def __init__(self, parent, data: DashboardData, on_done,
                 open_triggers=None):
        super().__init__(parent)
        self.data = data
        self.on_done = on_done
        self.open_triggers = open_triggers  # ledger texts for the verdict box
        self.title("Intrinsic value — Bear / Base / Bull")
        self.transient(parent)
        self.resizable(False, False)
        self.configure(background=P.PAGE)
        self.bind("<Escape>", lambda _e: self.destroy())  # FIX-12g
        self._wrap = int(560 * _display_dpi_of(self) / 96.0)  # dpi-true px
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
                  wraplength=self._wrap, justify="left").grid(
            row=1, column=0, columnspan=4, sticky="w", padx=10)

        self.help_lbl = ttk.Label(top, style="Secondary.TLabel",
                                  wraplength=self._wrap, justify="left")
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

        # FIX-14b: capex-normalized base prefill (house §2) — normalization
        # is the analyst's act, the prefill is the automation. Default stays
        # as-reported; the button fills the base entry with the suggestion.
        self._norm = normalized_base(data)
        self._capex_flag = capex_peak_flag(data)
        base_frame = ttk.Frame(top)
        base_frame.grid(row=4, column=0, columnspan=4, sticky="w", padx=6)
        self.basenorm_lbl = ttk.Label(base_frame, style="Secondary.TLabel",
                                      wraplength=self._wrap - 130,
                                      justify="left")
        self.basenorm_lbl.pack(side=tk.LEFT, padx=(4, 8))
        self.usenorm_btn = ttk.Button(base_frame, text="use normalized",
                                      command=self._use_normalized)
        self.usenorm_btn.pack(side=tk.LEFT)

        self.grid_frame = ttk.Frame(top)
        self.grid_frame.grid(row=5, column=0, columnspan=4, sticky="w", pady=(8, 4))

        self.estimates_lbl = ttk.Label(top, style="Secondary.TLabel",
                                       wraplength=self._wrap, justify="left")
        self.estimates_lbl.grid(row=6, column=0, columnspan=4, sticky="w", padx=10)

        # Phase-5 verdict inputs (§5.3): rating is judgment; the app only
        # checks it for coherence against the MoS (Control!B67 mechanics).
        verdict_frame = ttk.Frame(top)
        verdict_frame.grid(row=7, column=0, columnspan=4, sticky="w", padx=6,
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
            row=8, column=0, columnspan=4, sticky="w", padx=10, pady=(2, 0))

        btns = ttk.Frame(top)
        btns.grid(row=9, column=0, columnspan=4, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(btns, text="Compute", command=self._compute).pack(
            side=tk.RIGHT, padx=(0, 8))

        self._on_method(self._method_keys.index(self.method_var.get()))
        self.bind("<Return>", lambda _e: self._compute())
        self.grab_set()

    def _method_key(self) -> str:
        return self.method_var.get()

    def _use_normalized(self):
        # fills the base entry (plain $) with the through-cycle suggestion;
        # the value stays editable — the analyst owns the normalization
        if self._norm is not None:
            self.base_var.set(f"{self._norm[0]:.0f}")

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
        # FIX-14b base readout: dcf only (the RI base is BV₀, not FCFF)
        if method == "dcf" and self._norm is not None:
            y, p = self._norm
            x = self.data.fcff[-1] if self.data.fcff else None
            line = (f"base — as-reported {fmt_money(x)} · capex-normalized "
                    f"{fmt_money(y)} (5y median intensity {p:.1%})")
            if self._capex_flag:
                line += "  ⚠ capex peak/trough year"
            self.basenorm_lbl.configure(text=line)
            self.usenorm_btn.configure(state=tk.NORMAL)
        else:
            self.basenorm_lbl.configure(text="")
            self.usenorm_btn.configure(state=tk.DISABLED)
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

        # FIX-14a growth-anchor prefill (dcf): consensus is the Bull decade
        # case, Base = min(consensus, 5y CAGR, ROIC×RR), Bear = ½ Base —
        # analyst dispersion no longer maps to scenarios. Every seed stays
        # editable; terminal g keeps the 2.0% house default.
        anchors = build_growth_anchors(self.data) if method == "dcf" else None
        if anchors is not None and anchors.seeds:
            for case in CASE_NAMES:
                g = anchors.seeds.get(case)
                if g is not None:
                    self.cell_vars[(case, "g0")].set(f"{g * 100:.1f}")
                self.cell_vars[(case, "g_term")].set("2.0")
            self.estimates_lbl.configure(text=anchor_readout(anchors))
        elif method == "dcf":
            self.estimates_lbl.configure(
                text="No growth anchors available (no analyst estimates and "
                     "too little history) — enter your own growth cases.")
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
            cap = int(min(_display_dpi_of(self), 180))
            dpi = max(70, min(cap, int(viewport / FIG_W)))
            fig = render_valuation(self.data, res, dpi=dpi)
            verdict_fig = render_verdict(self.data, res, verdict, dpi=dpi,
                                         open_triggers=self.open_triggers)
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
        self.bind("<Escape>", lambda _e: self.destroy())  # FIX-12g
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
    _enable_windows_dpi_awareness()  # must precede tk.Tk() (FIX-12a)
    # FIX-12e: persisted settings (UA, default years) before any fetch is
    # possible; env vars keep precedence inside apply_user_settings
    config.apply_user_settings(config.load_user_settings())
    root = tk.Tk()
    apply_brand_theme(root)  # house colour scheme on every widget
    App(root)
    root.mainloop()
