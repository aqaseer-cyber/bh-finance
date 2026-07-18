"""v3 R1: frontend discipline tests — assets present and vendored (no
CDN, charter §6), the token reaches the page only via the bootstrap,
and no component introduces a color outside tokens.css (charter §1).
All offline."""
import re
from pathlib import Path

from fastapi.testclient import TestClient

from webui.server import create_app

STATIC = Path(__file__).resolve().parent.parent / "webui" / "static"

OWN_FILES = ["index.html", "app.js", "overview.js", "financials.js",
             "quality.js", "valuation.js", "watchlist.js",
             "fmt.js", "theme.js", "tokens.css"]
VENDORED = ["vendor/petite-vue.js", "vendor/echarts.min.js",
            "vendor/lightweight-charts.js", "vendor/VENDORED.json"]


def test_all_assets_exist_and_are_nonempty():
    for rel in OWN_FILES + VENDORED:
        p = STATIC / rel
        assert p.is_file() and p.stat().st_size > 0, rel


def test_index_references_only_local_assets():
    html = (STATIC / "index.html").read_text("utf-8")
    for src in re.findall(r'(?:src|href)="([^"]+)"', html):
        assert src.startswith("/static/"), src


def test_no_cdn_urls_in_our_frontend_files():
    for rel in OWN_FILES:
        text = (STATIC / rel).read_text("utf-8")
        assert "http://" not in text and "https://" not in text, rel


def test_no_color_values_outside_tokens(  ):
    """Charter §1: no component may introduce a color value not in the
    tokens file. Hex literals may exist ONLY in tokens.css."""
    hex_rx = re.compile(r"#[0-9a-fA-F]{3,8}\b")
    for rel in OWN_FILES:
        if rel == "tokens.css":
            continue
        text = (STATIC / rel).read_text("utf-8")
        assert not hex_rx.search(text), (rel, hex_rx.search(text))


def test_index_serves_with_token_injected():
    app = create_app(pipeline=lambda t, progress: None, token="sekret")
    client = TestClient(app,
                        headers={"Authorization": "Bearer sekret"})
    r = client.get("/")
    assert r.status_code == 200
    assert 'window.BHF_TOKEN = "sekret"' in r.text
    assert "%%TOKEN%%" not in r.text
    # static mount serves the tokens file
    css = client.get("/static/tokens.css")
    assert css.status_code == 200 and "--surface" in css.text


def test_vendored_manifest_records_versions():
    import json
    meta = json.loads((STATIC / "vendor/VENDORED.json")
                      .read_text("utf-8"))
    for lib in ("echarts", "lightweight-charts", "petite-vue"):
        assert meta.get(lib), lib
    assert "no CDN" in meta["source"]
