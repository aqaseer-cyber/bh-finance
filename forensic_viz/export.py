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
