import json

from sicau_net import config


def test_backoff_sequence():
    assert [config.backoff_delay(n) for n in range(0, 7)] == [0, 5, 10, 30, 60, 60, 60]


def test_load_defaults_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv(config.ENV_HOME, str(tmp_path))
    cfg = config.load()
    assert cfg.ssids[0] == "i_sicau_wifi6"
    assert cfg.poll_interval == config.DEFAULT_POLL_INTERVAL
    assert cfg.portal_host == config.DEFAULT_PORTAL_HOST
    assert cfg.base_url == "https://" + config.DEFAULT_PORTAL_HOST
    assert not (tmp_path / "config.json").exists()


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv(config.ENV_HOME, str(tmp_path))
    cfg = config.Config(username="202600000", ssids=["i_sicau_wifi6"], poll_interval=45)
    config.save(cfg)
    loaded = config.load()
    assert loaded.username == "202600000"
    assert loaded.ssids == ["i_sicau_wifi6"]
    assert loaded.poll_interval == 45


def test_load_ignores_unknown_keys_and_repairs_values(tmp_path, monkeypatch):
    monkeypatch.setenv(config.ENV_HOME, str(tmp_path))
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "username": "  202600000  ",
                "poll_interval": 1,
                "ssids": [],
                "bogus_key": "ignored",
            }
        ),
        encoding="utf-8",
    )
    cfg = config.load()
    assert cfg.username == "202600000"
    assert cfg.poll_interval == 5
    assert cfg.ssids == config.DEFAULT_SSIDS


def test_load_survives_broken_json(tmp_path, monkeypatch):
    monkeypatch.setenv(config.ENV_HOME, str(tmp_path))
    (tmp_path / "config.json").write_text("{not json", encoding="utf-8")
    cfg = config.load()
    assert cfg.poll_interval == config.DEFAULT_POLL_INTERVAL


def test_sanitize_splits_ssid_list(tmp_path, monkeypatch):
    monkeypatch.setenv(config.ENV_HOME, str(tmp_path))
    (tmp_path / "config.json").write_text(
        json.dumps({"ssids": [" i_sicau_wifi6 ", "", "i_sicau"]}), encoding="utf-8"
    )
    assert config.load().ssids == ["i_sicau_wifi6", "i_sicau"]
