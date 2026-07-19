"""FIX-12c acceptance tool: assert every report-PDF page fills ≥ 85% of
its A4 sheet on the constrained ("binding") axis' complement.

Usage:
    python tools/check_pdf_fill.py REPORT.pdf [figW,figH ...]

v3 R3b: the report is A4 portrait THROUGHOUT (P1..P6, appendix pages
included), so the default expectation is one portrait figure per PDF
page, however many pages the appendix flowed onto; pass explicit `W,H`
pairs to check a different sequence. Exits non-zero when any page falls
below 85% or renders on the wrong sheet.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pypdf import PdfReader  # noqa: E402

from forensic_viz.dashboard import A4P_H, FIG_W  # noqa: E402
from forensic_viz.export import page_size_for  # noqa: E402

PORTRAIT = (FIG_W, A4P_H)
THRESHOLD = 0.85


def page_fill(fig_w: float, fig_h: float) -> float:
    """Fill fraction on the non-binding axis after scale-to-fit."""
    pw, ph = page_size_for(fig_w, fig_h)
    s = min(pw / fig_w, ph / fig_h)
    return min(fig_w * s / pw, fig_h * s / ph)


def check(pdf_path: str, sizes) -> int:
    reader = PdfReader(pdf_path)
    if sizes is None:  # R3b default: every page is one portrait figure
        sizes = [PORTRAIT] * len(reader.pages)
    if len(reader.pages) != len(sizes):
        sizes = sizes[:len(reader.pages)]
    print(f"{'page':>4}  {'figure':>12}  {'A4 sheet':>10}  {'fill':>6}")
    worst, ok = 1.0, True
    for i, (page, (w, h)) in enumerate(zip(reader.pages, sizes), start=1):
        pw, ph = (float(page.mediabox.width), float(page.mediabox.height))
        want = page_size_for(w, h)
        orient = "portrait" if pw < ph else "landscape"
        fill = page_fill(w, h)
        worst = min(worst, fill)
        flag = "" if fill >= THRESHOLD else "  << BELOW 85%"
        if (round(pw, 1), round(ph, 1)) != (round(want[0], 1),
                                            round(want[1], 1)):
            flag += "  << WRONG SHEET"
        print(f"{i:>4}  {w:>5.2f}x{h:<5.2f}  {orient:>10}  {fill:>5.0%}{flag}")
        ok = ok and fill >= THRESHOLD and not flag.strip()
    print(f"worst fill: {worst:.0%} (threshold {THRESHOLD:.0%})")
    return 0 if ok else 1


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    sizes = None  # portrait per page (R3b)
    if len(sys.argv) > 2:
        sizes = [tuple(float(x) for x in a.split(","))
                 for a in sys.argv[2:]]
    return check(sys.argv[1], sizes)


if __name__ == "__main__":
    sys.exit(main())
