"""FIX-7 — house_assumptions.toml loader.

Tests the loader function directly (not a module-wide config reload, which is
import-order fragile) per the spec.
"""
from forensic_viz.config import _load_house


def test_load_house_from_env(monkeypatch, tmp_path):
    toml = tmp_path / "house.toml"
    toml.write_text("erp = 0.0423\nbeta_window_years = 7\n")
    monkeypatch.setenv("HOUSE_ASSUMPTIONS_FILE", str(toml))
    loaded = _load_house()
    assert loaded["erp"] == 0.0423
    assert loaded["beta_window_years"] == 7
    assert loaded["_path"] == str(toml)


def test_load_house_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("HOUSE_ASSUMPTIONS_FILE", str(tmp_path / "nope.toml"))
    monkeypatch.chdir(tmp_path)  # no house_assumptions.toml in an empty cwd
    assert _load_house() == {}


def test_example_file_matches_code_defaults():
    """The shipped example must carry the code defaults (spec: no real values)."""
    import pathlib

    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib
    from forensic_viz import config

    path = pathlib.Path(config.__file__).resolve().parent.parent / \
        "house_assumptions.example.toml"
    with open(path, "rb") as fh:
        ex = tomllib.load(fh)
    # loader defaults equal the example values (only meaningful when no real
    # house file is loaded in the test environment)
    if not config.HOUSE_LOADED:
        assert config.ERP_ASSUMPTION == ex["erp"]
        assert config.GDP_CAP == ex["gdp_cap"]
        assert config.BETA_WINDOW_YEARS == ex["beta_window_years"]
        assert config.STANDARD_FCFF_SHOCK == ex["standard_fcff_shock"]


def test_is_tie_tol_house_override(tmp_path, monkeypatch):
    """FIX-11e: is_tie_tol loads from the house file."""
    p = tmp_path / "house.toml"
    p.write_text("is_tie_tol = 0.05\n", encoding="utf-8")
    monkeypatch.setenv("HOUSE_ASSUMPTIONS_FILE", str(p))
    import importlib
    from forensic_viz import config as cfg
    importlib.reload(cfg)
    try:
        assert cfg.IS_TIE_TOL == 0.05
    finally:
        monkeypatch.delenv("HOUSE_ASSUMPTIONS_FILE")
        importlib.reload(cfg)


def test_segment_alias_table_round_trips(tmp_path, monkeypatch):
    """FIX-10e: a [segment_aliases.<TICKER>] table loads into the nested
    {TICKER: {old: canonical}} shape config expects."""
    p = tmp_path / "house.toml"
    p.write_text(
        "segment_history_years = 7\n"
        "segment_tie_tol = 0.03\n"
        "[segment_aliases.meli]\n"
        '"Marketplace" = "Commerce"\n'
        '"Mercado Pago" = "Fintech"\n',
        encoding="utf-8")
    monkeypatch.setenv("HOUSE_ASSUMPTIONS_FILE", str(p))
    import importlib
    from forensic_viz import config as cfg
    importlib.reload(cfg)
    try:
        assert cfg.SEGMENT_HISTORY_YEARS == 7
        assert cfg.SEGMENT_TIE_TOL == 0.03
        assert cfg.SEGMENT_ALIASES == {
            "MELI": {"Marketplace": "Commerce", "Mercado Pago": "Fintech"}}
    finally:
        monkeypatch.delenv("HOUSE_ASSUMPTIONS_FILE")
        importlib.reload(cfg)
