"""FIX-12 presentation helpers. Pure/headless-safe parts run everywhere;
anything that imports gui (and therefore tkinter) skips where tkinter is
absent — CI runners have tkinter without a display, which is the contract
these tests protect (import-safe, no Tk() at import time)."""
import pytest
from PIL import Image

from forensic_viz.workbook import asset_path


def test_icon_assets_exist_and_parse():
    ico, png = asset_path("app_icon.ico"), asset_path("app_icon.png")
    assert ico.is_file() and png.is_file()
    assert Image.open(png).size == (256, 256)
    Image.open(ico).verify()  # parses as a valid .ico


def test_asset_path_single_scheme():
    # the icon resolves through the same helper as the workbook shell
    assert asset_path("x.bin").parent == \
        asset_path("forensic_valuation_model_v3.xlsx").parent


def test_gui_helpers_headless_safe():
    tk = pytest.importorskip("tkinter")
    from forensic_viz import gui  # import must not construct Tk()

    gui._enable_windows_dpi_awareness()  # no-op off Windows, must not raise

    calls = []

    class FakeTkCmd:
        def call(self, *a):
            calls.append(a)

    class FakeRoot:
        tk = FakeTkCmd()

        def winfo_fpixels(self, spec):
            assert spec == "1i"
            return 120.0

    assert gui._apply_tk_scaling(FakeRoot()) == 120.0
    assert calls == [("tk", "scaling", 120.0 / 72.0)]

    class RaisingRoot:
        tk = FakeTkCmd()

        def winfo_fpixels(self, spec):
            raise tk.TclError("no display")

    assert gui._apply_tk_scaling(RaisingRoot()) == 96.0
    assert gui._display_dpi_of(RaisingRoot()) == 96.0


def test_should_rerender_threshold():
    tk = pytest.importorskip("tkinter")  # noqa: F841 — gui import needs it
    from forensic_viz.gui import _should_rerender
    assert _should_rerender(None, 96) is True     # first render
    assert _should_rerender(96, 96) is False
    assert _should_rerender(96, 101) is False     # < 6 dpi: debounced away
    assert _should_rerender(96, 102) is True
    assert _should_rerender(150, 96) is True      # shrink re-renders too
