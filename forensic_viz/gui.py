"""Tkinter desktop app: type a ticker, get the 5-year forensic dashboard.

Network fetches run on a worker thread; all Tk and matplotlib work stays on
the main thread (results are handed back through a queue polled with after()).
"""
from __future__ import annotations

import queue
import threading
import traceback
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from . import config
from .cache import Cache
from .dashboard import render_dashboard
from .demo_data import demo_dashboard_data
from .edgar import EdgarError
from .export import export_fundamentals_csv, export_prices_csv
from .metrics import DashboardData
from .pipeline import build_dashboard_data

SCREEN_DPI = 100  # on-screen render; PNG export re-renders at 150


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(f"Forensic Stock Viz {config.APP_VERSION} — 5-year performance dashboard")
        root.geometry("1180x860")
        root.minsize(900, 600)

        self.queue: "queue.Queue[tuple]" = queue.Queue()
        self.data: Optional[DashboardData] = None
        self.fig = None
        self.fig_canvas: Optional[FigureCanvasTkAgg] = None
        self.busy = False

        bar = ttk.Frame(root, padding=(10, 8))
        bar.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(bar, text="Ticker:").pack(side=tk.LEFT)
        self.ticker_var = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.ticker_var, width=10)
        entry.pack(side=tk.LEFT, padx=(6, 8))
        entry.bind("<Return>", lambda _e: self.analyze())
        entry.focus_set()
        self.analyze_btn = ttk.Button(bar, text="Analyze", command=self.analyze)
        self.analyze_btn.pack(side=tk.LEFT)
        self.demo_btn = ttk.Button(bar, text="Offline demo", command=self.demo)
        self.demo_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.save_btn = ttk.Button(bar, text="Save PNG…", command=self.save_png,
                                   state=tk.DISABLED)
        self.save_btn.pack(side=tk.LEFT, padx=(16, 0))
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
        self.view.configure(yscrollcommand=vbar.set)
        vbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.inner = ttk.Frame(self.view)
        self.inner_id = self.view.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._sync_scrollregion)
        self.view.bind_all("<MouseWheel>", self._on_mousewheel)      # Windows/macOS
        self.view.bind_all("<Button-4>", self._on_mousewheel_linux)  # X11
        self.view.bind_all("<Button-5>", self._on_mousewheel_linux)

        self.root.after(120, self._poll_queue)

    # ------------------------------------------------------------ scrolling

    def _sync_scrollregion(self, _event=None):
        self.view.configure(scrollregion=self.view.bbox("all"))

    def _on_mousewheel(self, event):
        self.view.yview_scroll(int(-event.delta / 120) * 3, "units")

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
            )
            self.queue.put(("data", data))
        except EdgarError as exc:
            self.queue.put(("error", str(exc)))
        except Exception:
            self.queue.put(("error", "Unexpected error:\n" + traceback.format_exc(limit=3)))

    def _demo_worker(self):
        try:
            self.queue.put(("data", demo_dashboard_data()))
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
        self.root.after(120, self._poll_queue)

    def _show(self, data: DashboardData):
        self.status_var.set("Rendering…")
        self.root.update_idletasks()
        fig = render_dashboard(data, dpi=SCREEN_DPI)
        if self.fig_canvas is not None:
            self.fig_canvas.get_tk_widget().destroy()
        self.data, self.fig = data, fig
        self.fig_canvas = FigureCanvasTkAgg(fig, master=self.inner)
        self.fig_canvas.draw()
        self.fig_canvas.get_tk_widget().pack()
        self.view.yview_moveto(0)
        note = ""
        if data.price_error:
            note = "  (price sources unavailable — fundamentals only)"
        self._set_busy(False, f"{data.company} — done.{note}")
        self.save_btn.configure(state=tk.NORMAL)
        self.csv_btn.configure(state=tk.NORMAL)

    def save_png(self):
        if self.fig is None or self.data is None:
            return
        default = f"{self.data.ticker}_5y_dashboard_{self.data.generated.isoformat()}.png"
        path = filedialog.asksaveasfilename(
            defaultextension=".png", initialfile=default,
            filetypes=[("PNG image", "*.png")])
        if not path:
            return
        self.fig.savefig(path, dpi=150)
        self.status_var.set(f"Saved {path}")

    def export_csv(self):
        if self.data is None:
            return
        default = f"{self.data.ticker}_5y_fundamentals_{self.data.generated.isoformat()}.csv"
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", initialfile=default,
            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        export_fundamentals_csv(self.data, path)
        written = [path]
        if self.data.price_dates:
            p = Path(path)
            price_path = str(p.with_name(p.stem + "_prices" + p.suffix))
            export_prices_csv(self.data, price_path)
            written.append(price_path)
        self.status_var.set("Saved " + " and ".join(written))

    def _set_busy(self, busy: bool, status: str):
        self.busy = busy
        state = tk.DISABLED if busy else tk.NORMAL
        self.analyze_btn.configure(state=state)
        self.demo_btn.configure(state=state)
        self.status_var.set(status)


def run_gui():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")  # native look on Windows
    except tk.TclError:
        pass
    App(root)
    root.mainloop()
