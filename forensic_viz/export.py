"""Exports: the multi-page A4 PDF report (v3 R3: the audit CSVs are
retired - provenance lives in the workbook tag notes and the goldens)."""
from __future__ import annotations

from typing import Optional

from .metrics import DashboardData


A4_PT = (595.276, 841.890)  # ISO A4 portrait, PostScript points


def page_size_for(w: float, h: float) -> tuple:
    """A4 orientation per page (FIX-12c): portrait for tall figures,
    landscape otherwise — no more half-empty portrait pages."""
    portrait = (h / w) >= 1.2 if w else True
    return A4_PT if portrait else (A4_PT[1], A4_PT[0])


def export_pdf(figures, path: str) -> None:
    """All report pages into one PDF, every page normalized to A4 portrait.

    Figures render at their native size (vector), then each page is scaled to
    fit and centered on a true A4 canvas — appearance is preserved exactly,
    and the printed document is uniform. Falls back to native page sizes if
    pypdf is unavailable.
    """
    import io

    from matplotlib.backends.backend_pdf import PdfPages

    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        for fig in figures:
            if fig is not None:
                pdf.savefig(fig)
    buf.seek(0)
    try:
        from pypdf import PdfReader, PdfWriter, Transformation
        reader, writer = PdfReader(buf), PdfWriter()
        for src in reader.pages:
            page = writer.add_page(src)  # attach first (pypdf 6+ contract)
            w, h = float(page.mediabox.width), float(page.mediabox.height)
            a4w, a4h = page_size_for(w, h)  # per-page orientation (FIX-12c)
            s = min(a4w / w, a4h / h)
            tx, ty = (a4w - w * s) / 2, (a4h - h * s) / 2
            page.add_transformation(
                Transformation().scale(s, s).translate(tx, ty))
            page.mediabox.lower_left = (0, 0)
            page.mediabox.upper_right = (a4w, a4h)
            if page.cropbox is not None:
                page.cropbox.lower_left = (0, 0)
                page.cropbox.upper_right = (a4w, a4h)
        with open(path, "wb") as fh:
            writer.write(fh)
    except ImportError:
        with open(path, "wb") as fh:
            fh.write(buf.getvalue())


# ------------------------------------------------- v3 R3d: the run bundle

class ConsistencyError(RuntimeError):
    """Principle 2 violated: the artifacts of one run disagree on the
    verdict numbers — the export aborts with the diff."""


def _sha256(path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_model_decision(model_path):
    """(fv_avg, mos) from the workbook Cover's decision rows."""
    from openpyxl import load_workbook

    cov = load_workbook(model_path, read_only=True)["Cover"]
    rows = {str(row[0].value or ""): row[1].value
            for row in cov.iter_rows(min_col=1, max_col=2)}
    return rows.get("FV average"), rows.get("MoS at P₀")


def _read_shell_stamp(shell_path):
    """{'fv_avg':…, 'mos':…} parsed from the Control!B7 run stamp."""
    import re

    from openpyxl import load_workbook

    cell = load_workbook(shell_path)["Control"]["B7"]
    text = cell.comment.text if cell.comment else ""
    out = {}
    m = re.search(r"FV_avg ([-\d.e+]+)", text)
    if m:
        out["fv_avg"] = float(m.group(1))
    m = re.search(r"MoS ([-\d.e+]+)", text)
    if m:
        out["mos"] = float(m.group(1))
    return out


def assert_run_consistency(verdict, model_path=None,
                           shell_path=None) -> None:
    """FV/MoS equality across the run's artifacts vs the verdict object
    (the report prints from that same object). Mismatch -> abort with
    the diff (design principle 2). Money compared at $0.005, MoS at
    1e-6 — anything beyond XML float round-trip is a corruption."""
    diffs = []

    def check(artifact, field, got, want, tol):
        if want is None:
            return
        if got is None or abs(got - want) > tol:
            diffs.append(f"{artifact} {field}: {got!r} != verdict {want!r}")

    if model_path is not None:
        fv, mos = _read_model_decision(model_path)
        check("model Cover", "FV average", fv, verdict.fv_avg, 0.005)
        check("model Cover", "MoS", mos, verdict.mos, 1e-6)
    if shell_path is not None:
        stamp = _read_shell_stamp(shell_path)
        check("shell stamp", "FV average", stamp.get("fv_avg"),
              verdict.fv_avg, 0.005)
        check("shell stamp", "MoS", stamp.get("mos"), verdict.mos, 1e-6)
    if diffs:
        raise ConsistencyError(
            "cross-artifact consistency FAILED — the run's artifacts "
            "disagree on the verdict numbers:\n  " + "\n  ".join(diffs))


def export_run(d, res=None, verdict=None, out_dir=".", dpi=None,
               open_triggers=None, prior=None, report_path=None,
               model_path=None, shell_path=None) -> dict:
    """One command, one run, all artifacts (design R3d): the report PDF,
    the model workbook, the forensic-shell fill (when a valuation is
    attached — a shell without a valuation would be an empty claim), and
    the run-manifest JSON, all sharing `{TICKER}_{date}_{run_id}_…`
    names. The consistency contract runs BEFORE the manifest is written:
    an inconsistent run never gets a receipt. Returns the manifest dict.

    Explicit *_path overrides win over the unified naming (the analyst's
    chosen path is never second-guessed)."""
    import datetime as _dt
    import json
    from pathlib import Path

    from .dashboard import DPI, render_report
    from .model_export import export_financial_model
    from .runid import artifact_name, provider_set, run_identity

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rid, ihash = run_identity(d, res)

    def target(override, kind):
        return Path(override) if override else out / artifact_name(
            d, res, kind)

    report = target(report_path, "report")
    figs = render_report(d, res, verdict, open_triggers=open_triggers,
                         prior=prior, dpi=dpi or DPI)
    export_pdf(figs, str(report))

    model = target(model_path, "model")
    export_financial_model(d, str(model), res=res, verdict=verdict)

    shell = None
    if verdict is not None:
        from .workbook import fill_workbook
        shell = target(shell_path, "shell")
        fill_workbook(d, str(shell), res=res, verdict=verdict)
        assert_run_consistency(verdict, model_path=model, shell_path=shell)

    artifacts = {"report": report, "model": model}
    if shell is not None:
        artifacts["shell"] = shell
    manifest = {
        "schema": 1,
        "ticker": d.ticker,
        "company": d.company,
        "run_id": rid,
        "input_hash": ihash,
        "generated": d.generated.isoformat(),
        "written_at": _dt.datetime.now(_dt.timezone.utc).isoformat(
            timespec="seconds"),
        "app_version": __import__(
            "forensic_viz.config", fromlist=["APP_VERSION"]).APP_VERSION,
        "providers": provider_set(d),
        "rating": verdict.rating if verdict is not None else None,
        "fv_avg": verdict.fv_avg if verdict is not None else None,
        "mos": verdict.mos if verdict is not None else None,
        "stressed_mos": (verdict.stressed_mos
                         if verdict is not None else None),
        "warnings": (len(d.health_notes or [])
                     + (len(res.warnings)
                        + sum(len(c.warnings) for c in res.cases)
                        if res is not None else 0)),
        "artifacts": {kind: {"path": str(p), "sha256": _sha256(p),
                             "bytes": p.stat().st_size}
                      for kind, p in artifacts.items()},
    }
    if shell is None:
        manifest["shell"] = ("omitted — no valuation attached to this "
                             "run (no silent absence)")
    manifest_path = out / artifact_name(d, res, "manifest")
    manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2),
                             encoding="utf-8")
    return manifest
