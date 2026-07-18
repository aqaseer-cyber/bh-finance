"""Asset-path helpers (the Tk gui helper tests died with gui.py in
v3 R3)."""
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
