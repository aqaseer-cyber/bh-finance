"""FIX-12e: persisted user settings — round-trip, corruption tolerance,
env-var precedence, and the attribute edgar actually reads at call time."""
import pytest

from forensic_viz import config


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    """Isolated app-data dir + a snapshot/restore of the mutable settings
    attributes (apply_user_settings writes module globals)."""
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("SEC_EDGAR_USER_AGENT", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    saved = (config.SEC_USER_AGENT, config.UA_IS_PLACEHOLDER,
             config.USER_HOUSE_FILE, config.GUI_DEFAULT_YEARS)
    yield config
    (config.SEC_USER_AGENT, config.UA_IS_PLACEHOLDER,
     config.USER_HOUSE_FILE, config.GUI_DEFAULT_YEARS) = saved


def test_settings_round_trip(cfg, tmp_path):
    s = {"sec_user_agent": "Jane Doe jane@example.com", "default_years": 7}
    cfg.save_user_settings(s)
    assert cfg.settings_path().is_file()
    assert str(cfg.settings_path()).startswith(str(tmp_path))
    assert cfg.load_user_settings() == s


def test_missing_and_corrupted_files_load_as_empty(cfg):
    assert cfg.load_user_settings() == {}          # absent
    p = cfg.settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    assert cfg.load_user_settings() == {}          # corrupted
    p.write_text('["a", "list"]', encoding="utf-8")
    assert cfg.load_user_settings() == {}          # wrong shape


def test_apply_fills_ua_gap_and_records_house_file(cfg):
    cfg.apply_user_settings({"sec_user_agent": "Jane Doe jane@example.com",
                             "house_file": "/x/house.toml",
                             "default_years": 5})
    assert cfg.SEC_USER_AGENT == "Jane Doe jane@example.com"
    assert cfg.UA_IS_PLACEHOLDER is False
    assert cfg.USER_HOUSE_FILE == "/x/house.toml"
    assert cfg.GUI_DEFAULT_YEARS == 5


def test_env_var_beats_settings_file(cfg, monkeypatch):
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "Env Person env@example.com")
    before = cfg.SEC_USER_AGENT
    cfg.apply_user_settings({"sec_user_agent": "File Person file@example.com"})
    assert cfg.SEC_USER_AGENT == before            # saved UA ignored
    assert cfg.SEC_USER_AGENT != "File Person file@example.com"


def test_invalid_years_choice_is_ignored(cfg):
    before = cfg.GUI_DEFAULT_YEARS
    cfg.apply_user_settings({"default_years": 4})
    assert cfg.GUI_DEFAULT_YEARS == before
    cfg.apply_user_settings({"default_years": "seven"})
    assert cfg.GUI_DEFAULT_YEARS == before


def test_every_offered_years_choice_round_trips(cfg):
    """Regression (FIX-16f): the Years combobox gained 15 but the
    validator still pinned (3, 5, 7, 10), silently discarding a saved 15.
    gui.YEAR_CHOICES now derives from config.YEAR_WINDOW_CHOICES, so every
    offered value must apply."""
    assert 15 in cfg.YEAR_WINDOW_CHOICES
    for y in cfg.YEAR_WINDOW_CHOICES:
        cfg.apply_user_settings({"default_years": y})
        assert cfg.GUI_DEFAULT_YEARS == y


def test_edgar_session_reads_the_mutated_attribute(cfg):
    """Regression for the import-style trap: edgar must read
    config.SEC_USER_AGENT at session-construction time, so the Settings
    dialog's mutation reaches real requests."""
    from forensic_viz.cache import Cache
    from forensic_viz.edgar import _SecSession

    cfg.apply_user_settings({"sec_user_agent": "Jane Doe jane@example.com"})
    sess = _SecSession(Cache())
    assert sess.session.headers["User-Agent"] == "Jane Doe jane@example.com"


def test_saved_house_file_is_a_load_candidate(cfg, tmp_path):
    """The Settings dialog's house_file takes effect next launch because
    _load_house re-reads settings.json at config import."""
    toml = tmp_path / "my_house.toml"
    toml.write_text("erp = 0.055\n", encoding="utf-8")
    cfg.save_user_settings({"house_file": str(toml)})
    out = cfg._load_house()
    assert out.get("erp") == 0.055
    assert out.get("_path") == str(toml)
