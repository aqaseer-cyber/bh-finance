"""FIX-17g: the pure hover-readout — nearest point per line, honest
dashes on masked stretches, date headers, unnamed-line fallback, and
the 3-series cap. The Tk crosshair layer only places this text."""
import math

from matplotlib.dates import date2num
import datetime as dt

from forensic_viz.explore import hover_readout


def test_nearest_point_and_date_header():
    days = [dt.date(2026, 1, 1) + dt.timedelta(days=7 * i)
            for i in range(10)]
    xs = [date2num(d) for d in days]
    ys = [100.0 + i for i in range(10)]
    x = date2num(dt.date(2026, 1, 16))          # nearest: index 2
    out = hover_readout([("close", xs, ys)], x, is_date=True)
    assert out.startswith("2026-01-15")
    assert "close 102.00" in out


def test_masked_stretch_reads_dash_not_number():
    xs = list(range(10))
    ys = [1.0, 2.0, float("nan"), 4.0] + [5.0] * 6
    out = hover_readout([("P/E (TTM)", xs, ys)], 2.2)
    assert "P/E (TTM) –" in out
    assert "nan" not in out.lower()


def test_unnamed_lines_fall_back_to_value_and_cap():
    xs = list(range(8))
    out = hover_readout([("_child0", xs, [float(i) for i in xs])], 3.0)
    assert "value 3.00" in out
    lines = [(f"s{i}", xs, [float(i)] * 8) for i in range(5)]
    out2 = hover_readout(lines, 1.0)
    assert "s2" in out2 and "s3" not in out2    # capped at 3 series


def test_degenerate_inputs_return_empty():
    assert hover_readout([], 1.0) == ""
    assert hover_readout([("x", [1.0], [2.0])], 1.0) == ""       # 1 point
    assert hover_readout([("x", [1, 2, 3], [1.0, 2.0])], 1.0) == ""
