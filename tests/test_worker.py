import pytest

from sicau_net import portal, wifi
from sicau_net import worker as worker_module
from sicau_net.config import Config
from sicau_net.credentials import Credentials
from sicau_net.worker import LoginWorker, State

CREDS = Credentials(username="202600000", password="pw")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """别让测试真的睡过去。"""
    monkeypatch.setattr(worker_module.time, "sleep", lambda seconds: None)


def make_worker(cfg, creds, on_change=None):
    return LoginWorker(lambda: cfg, lambda: creds, on_change=on_change)


def offline(*args, **kwargs):
    return portal.ProbeResult(False, {}, "HTTP 302")


def online(*args, **kwargs):
    return portal.ProbeResult(True, {}, "HTTP 204")


def test_cycle_reports_online(monkeypatch):
    monkeypatch.setattr(portal, "probe", online)
    status = make_worker(Config(), CREDS)._cycle()
    assert status.state is State.ONLINE


def test_cycle_without_credentials():
    status = make_worker(Config(), None)._cycle()
    assert status.state is State.NO_CREDENTIALS


def test_cycle_when_manually_offline(monkeypatch):
    monkeypatch.setattr(portal, "probe", offline)
    worker = make_worker(Config(), CREDS)
    worker._paused = True
    assert worker._cycle().state is State.PAUSED


def test_cycle_skips_foreign_wifi(monkeypatch):
    monkeypatch.setattr(portal, "probe", offline)
    monkeypatch.setattr(wifi, "current_ssid", lambda: "ChinaNet-xyz")
    worker = make_worker(Config(auto_connect_wifi=False), CREDS)
    status = worker._cycle()
    assert status.state is State.SKIPPED
    assert "ChinaNet-xyz" in status.message


def test_cycle_logs_in_on_campus_wifi(monkeypatch):
    calls = []
    monkeypatch.setattr(portal, "probe", offline)
    monkeypatch.setattr(wifi, "current_ssid", lambda: "i_sicau_wifi6")
    monkeypatch.setattr(
        portal,
        "login",
        lambda cfg, user, pwd, params=None: calls.append((user, pwd, params))
        or portal.Result(True, "认证成功"),
    )
    status = make_worker(Config(), CREDS)._cycle()
    assert status.state is State.ONLINE
    assert calls == [("202600000", "pw", {})]


def test_cycle_passes_probe_params_to_login(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        portal, "probe", lambda *a, **k: portal.ProbeResult(False, {"wlanuserip": "10.0.0.5"}, "302")
    )
    monkeypatch.setattr(wifi, "current_ssid", lambda: "i_sicau_wifi6")
    monkeypatch.setattr(
        portal,
        "login",
        lambda cfg, user, pwd, params=None: seen.update(params) or portal.Result(True, "ok"),
    )
    make_worker(Config(), CREDS)._cycle()
    assert seen == {"wlanuserip": "10.0.0.5"}


def test_backoff_grows_after_failures(monkeypatch):
    monkeypatch.setattr(portal, "probe", offline)
    monkeypatch.setattr(wifi, "current_ssid", lambda: "i_sicau_wifi6")
    monkeypatch.setattr(portal, "login", lambda *a, **k: portal.Result(False, "密码错误"))
    worker = make_worker(Config(), CREDS)

    expected = [5, 10, 30, 60, 60]
    for seconds in expected:
        assert worker._cycle().failures >= 1
        assert worker._interval() == seconds


def test_failures_reset_after_recovery(monkeypatch):
    monkeypatch.setattr(portal, "probe", offline)
    monkeypatch.setattr(wifi, "current_ssid", lambda: "i_sicau_wifi6")
    monkeypatch.setattr(portal, "login", lambda *a, **k: portal.Result(False, "x"))
    worker = make_worker(Config(), CREDS)
    worker._cycle()
    worker._cycle()
    assert worker._failures == 2

    monkeypatch.setattr(portal, "probe", online)
    assert worker._cycle().state is State.ONLINE
    assert worker._failures == 0
    assert worker._interval() == Config().poll_interval


def test_auto_connect_wifi_then_login(monkeypatch):
    connected = []
    monkeypatch.setattr(portal, "probe", offline)
    monkeypatch.setattr(
        wifi, "current_ssid", lambda: "i_sicau_wifi6" if connected else "Home-WiFi"
    )
    monkeypatch.setattr(wifi, "wireless_profiles", lambda: ["Home-WiFi", "i_sicau_wifi6"])
    monkeypatch.setattr(wifi, "interface_name", lambda: "thinkpad")
    monkeypatch.setattr(
        wifi, "connect", lambda ssid, interface=None: connected.append(ssid) or True
    )
    monkeypatch.setattr(wifi, "wait_for_ipv4", lambda timeout=15.0: "10.23.13.100")
    monkeypatch.setattr(portal, "login", lambda *a, **k: portal.Result(True, "认证成功"))

    status = make_worker(Config(), CREDS)._cycle()
    assert connected == ["i_sicau_wifi6"]
    assert status.state is State.ONLINE


def test_auto_connect_skipped_when_profile_missing(monkeypatch):
    monkeypatch.setattr(portal, "probe", offline)
    monkeypatch.setattr(wifi, "current_ssid", lambda: None)
    monkeypatch.setattr(wifi, "wireless_profiles", lambda: ["SomeOtherWiFi"])
    monkeypatch.setattr(portal, "login", lambda *a, **k: portal.Result(True, "ok"))

    status = make_worker(Config(), CREDS)._cycle()
    assert status.state is State.ONLINE


def test_publish_reaches_callback(monkeypatch):
    seen = []
    monkeypatch.setattr(portal, "probe", online)
    worker = make_worker(Config(), CREDS, on_change=seen.append)
    worker._publish(worker._cycle())
    assert seen and seen[-1].state is State.ONLINE


def test_start_publishes_first_status(monkeypatch):
    import threading

    monkeypatch.setattr(portal, "probe", online)
    seen = []
    done = threading.Event()

    def on_change(status):
        seen.append(status)
        done.set()

    worker = make_worker(Config(), CREDS, on_change=on_change)
    worker.start()
    try:
        assert done.wait(5), "守护线程没有在 5 秒内上报状态"
    finally:
        worker.stop()
    assert seen[0].state is State.ONLINE


def test_callback_exception_does_not_break_worker(monkeypatch):
    def boom(status):
        raise RuntimeError("callback exploded")

    monkeypatch.setattr(portal, "probe", online)
    worker = make_worker(Config(), CREDS, on_change=boom)
    assert worker._cycle().state is State.ONLINE


def test_sleep_wakes_early_on_trigger():
    worker = make_worker(Config(), CREDS)
    worker._wake.set()
    assert worker._sleep(10) is True


def test_sleep_returns_when_stopped():
    worker = make_worker(Config(), CREDS)
    worker._stop.set()
    assert worker._sleep(10) is True


def test_manual_logout_pauses_auto_login(monkeypatch):
    monkeypatch.setattr(portal, "logout", lambda *a, **k: portal.Result(True, "已离线"))
    monkeypatch.setattr(portal, "probe", offline)
    worker = make_worker(Config(), CREDS)
    assert worker.logout_now().ok
    assert worker.paused is True
    assert worker._cycle().state is State.PAUSED


def test_manual_login_resumes(monkeypatch):
    monkeypatch.setattr(portal, "login", lambda *a, **k: portal.Result(True, "认证成功"))
    monkeypatch.setattr(portal, "probe", online)
    worker = make_worker(Config(), CREDS)
    worker._paused = True
    assert worker.login_now().ok
    assert worker.paused is False

