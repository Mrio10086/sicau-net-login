import pytest

from sicau_net import portal
from sicau_net.config import Config

REDIRECT_PARAMS = (
    "wlanacip=10.23.13.100&wlanacname=YA-XX-Bras01-ME60-X8A"
    "&wlanuserip=10.23.13.100&mac=AA:BB:CC:DD:EE:FF&vlan=700&act=&errorMsg=&url="
)
REDIRECT_LOCATION = (
    "https://portal.sicau.edu.cn/index_auth.jsp;JSESSIONID-BOSS-1=ABC?" + REDIRECT_PARAMS
)

ONLINE_PAGE = (
    "<html><body><form id=\"goLoginForm\" method=\"post\">"
    "<input id=\"userId\" name=\"userId\" value=\"\" />"
    "<input id=\"passwd\" name=\"passwd\" value=\"\" />"
    "<input id=\"distoken\" name=\"distoken\" value=\"tok\" />"
    "<input id=\"pageid\" name=\"pageid\" value=\"201\" />"
    "</form><div class=\"login_out\"><p>您已成功登录校园网!</p>"
    "<button id=\"online\" type=\"button\">离线</button></div></body></html>"
)


class FakeResponse:
    def __init__(self, status_code=200, text="", headers=None, payload=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    def __init__(self, get_handler, post_handler):
        self._get_handler = get_handler
        self._post_handler = post_handler
        self.calls = []
        self.headers = {}

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self._get_handler(url, kwargs)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self._post_handler(url, kwargs)

    def close(self):
        pass


def install_session(monkeypatch, get_handler, post_handler):
    sessions = []
    # 测试里不要真的去解析域名
    monkeypatch.setattr(portal, "dns_ok", lambda *args, **kwargs: True)

    def factory():
        session = FakeSession(get_handler, post_handler)
        sessions.append(session)
        return session

    monkeypatch.setattr(portal.requests, "Session", factory)
    return sessions


def portal_login_page(login_html):
    def get_handler(url, kwargs):
        if "webdisconnweb.do" in url:
            return FakeResponse(302, headers={"Location": REDIRECT_LOCATION})
        return FakeResponse(200, text=login_html)

    return get_handler


# ---------- 表单解析 ----------


def test_parse_login_form_finds_goLoginForm(login_html):
    form = portal.parse_login_form(login_html)
    assert form is not None
    assert form.is_login_form
    assert form.fields["userId"] == ""
    assert form.fields["passwd"] == ""
    assert form.fields["pageid"] == "201"


def test_parse_login_form_skips_disabled_but_reads_url_parameter(login_html):
    form = portal.parse_login_form(login_html)
    # disabled 的字段浏览器不会提交
    assert "wlanuserip" not in form.fields
    assert "urlParameter" not in form.fields
    # 但 JS 会读它的值来拼提交地址
    assert form.url_parameter.startswith("wlanacip=10.23.13.100")
    assert "wlanuserip=10.23.13.100" in form.url_parameter
    assert form.url_parameter.endswith("url=")


def test_parse_login_form_returns_none_without_form():
    assert portal.parse_login_form("<html><body>nothing here</body></html>") is None


def test_page_state_detects_login_and_online(login_html):
    assert portal.page_state(login_html) == "login"
    assert portal.page_state(ONLINE_PAGE) == "online"
    assert portal.page_state("<html></html>") == "unknown"


def test_build_login_payload_overrides_credentials(login_html):
    form = portal.parse_login_form(login_html)
    payload = portal.build_login_payload(form, "202600000", "p@ssw0rd")
    assert payload["userId"] == "202600000"
    assert payload["passwd"] == "p@ssw0rd"
    assert payload["isRemind"] == "0"
    # 页面原有字段保持原样
    assert payload["pageid"] == "201"
    assert payload["templatetype"] == "1"
    assert payload["distoken"] == ""


def test_submit_query_prefers_url_parameter(login_html):
    form = portal.parse_login_form(login_html)
    assert portal.submit_query(form, {"wlanuserip": "1.2.3.4"}).startswith("wlanacip=")
    empty = portal.LoginForm()
    assert portal.submit_query(empty, {"wlanuserip": "1.2.3.4"}) == "wlanuserip=1.2.3.4"


# ---------- URL / 文本工具 ----------


def test_params_from_url_keeps_blank_values():
    params = portal.params_from_url(REDIRECT_LOCATION)
    assert params["wlanuserip"] == "10.23.13.100"
    assert params["act"] == ""
    assert params["url"] == ""
    assert portal.params_from_url("") == {}


def test_extract_error_prefers_err_message():
    html = '<input id="errMessage" value="该账号已在别处登录" />'
    assert portal.extract_error(html) == "该账号已在别处登录"


def test_extract_error_from_visible_text():
    html = "<html><script>var a = '密码错误';</script><body><p>密码错误，请重试</p></body></html>"
    assert "密码错误" in portal.extract_error(html)


def test_extract_error_returns_empty_on_success_page():
    assert portal.extract_error("<html><body>您已成功登录校园网!</body></html>") == ""


def test_visible_text_drops_markup():
    assert portal.visible_text("<p>你好</p>\n<script>x</script>") == "你好"


def test_login_page_url_appends_query():
    cfg = Config()
    assert portal.login_page_url(cfg, None) == "https://portal.sicau.edu.cn/webauth.do"
    url = portal.login_page_url(cfg, {"wlanuserip": "10.0.0.2"})
    assert url.endswith("/webauth.do?wlanuserip=10.0.0.2")


# ---------- 在线探测 ----------


def test_probe_online(monkeypatch):
    monkeypatch.setattr(portal.requests, "get", lambda *a, **k: FakeResponse(204))
    result = portal.probe(Config())
    assert result.online
    assert result.params == {}


def test_probe_offline_reads_redirect_params(monkeypatch):
    monkeypatch.setattr(
        portal.requests,
        "get",
        lambda *a, **k: FakeResponse(302, headers={"Location": REDIRECT_LOCATION}),
    )
    result = portal.probe(Config())
    assert not result.online
    assert result.params["wlanuserip"] == "10.23.13.100"
    assert result.params["wlanacname"] == "YA-XX-Bras01-ME60-X8A"


def test_probe_offline_without_params(monkeypatch):
    monkeypatch.setattr(portal.requests, "get", lambda *a, **k: FakeResponse(200, text="portal"))
    result = portal.probe(Config())
    assert not result.online
    assert result.params == {}


def test_probe_handles_network_error(monkeypatch):
    def boom(*args, **kwargs):
        raise portal.requests.ConnectionError("no route")

    monkeypatch.setattr(portal.requests, "get", boom)
    result = portal.probe(Config())
    assert not result.online
    assert "ConnectionError" in result.detail


# ---------- 参数发现 ----------


def test_discover_params_prefers_seed_without_network():
    params, source = portal.discover_params(None, Config(), seed={"wlanuserip": "10.0.0.9"})
    assert params["wlanuserip"] == "10.0.0.9"
    assert source == "探测重定向"


def test_discover_params_uses_portal_redirect():
    session = FakeSession(
        lambda url, kwargs: FakeResponse(302, headers={"Location": REDIRECT_LOCATION}),
        lambda url, kwargs: None,
    )
    params, source = portal.discover_params(session, Config())
    assert params["wlanuserip"] == "10.23.13.100"
    assert source == "门户 302"


def test_discover_params_falls_back_to_local(monkeypatch):
    monkeypatch.setattr(portal.wifi, "local_ipv4", lambda: "10.23.13.100")
    session = FakeSession(lambda url, kwargs: FakeResponse(200, text="x"), lambda u, k: None)
    params, source = portal.discover_params(session, Config())
    assert source == "本地拼装"
    assert params["wlanuserip"] == "10.23.13.100"
    assert params["wlanacname"] == Config().ac_name


# ---------- 登录 / 离线 ----------


def test_login_posts_parsed_form(monkeypatch, login_html):
    captured = {}

    def post_handler(url, kwargs):
        captured["url"] = url
        captured["data"] = kwargs["data"]
        return FakeResponse(200, text="<html><body>认证成功</body></html>")

    install_session(monkeypatch, portal_login_page(login_html), post_handler)
    monkeypatch.setattr(portal, "wait_online", lambda *a, **k: True)

    result = portal.login(Config(), "202600000", "p@ssw0rd")
    assert result.ok
    assert captured["url"].startswith("https://portal.sicau.edu.cn/webauth.do?")
    assert "wlanuserip=10.23.13.100" in captured["url"]
    data = captured["data"]
    assert data["userId"] == "202600000"
    assert data["passwd"] == "p@ssw0rd"
    assert data["isRemind"] == "0"
    assert data["pageid"] == "201"
    assert "wlanuserip" not in data


def test_login_reports_portal_error(monkeypatch, login_html):
    def post_handler(url, kwargs):
        return FakeResponse(200, text="<html><body>密码错误，请重新输入</body></html>")

    install_session(monkeypatch, portal_login_page(login_html), post_handler)
    monkeypatch.setattr(portal, "wait_online", lambda *a, **k: False)

    result = portal.login(Config(), "202600000", "wrong")
    assert not result.ok
    assert "密码错误" in result.message


def test_login_reports_probe_failure(monkeypatch, login_html):
    install_session(
        monkeypatch,
        portal_login_page(login_html),
        lambda url, kwargs: FakeResponse(200, text="<html><body>ok</body></html>"),
    )
    monkeypatch.setattr(portal, "wait_online", lambda *a, **k: False)

    result = portal.login(Config(), "202600000", "p@ssw0rd")
    assert not result.ok
    assert "未联网" in result.message


def test_login_when_portal_says_online(monkeypatch):
    install_session(
        monkeypatch,
        lambda url, kwargs: FakeResponse(200, text=ONLINE_PAGE),
        lambda url, kwargs: pytest.fail("已在线时不应提交表单"),
    )
    result = portal.login(Config(), "202600000", "p@ssw0rd")
    assert result.ok
    assert "已在线" in result.message


def test_login_requires_credentials():
    result = portal.login(Config(), "", "")
    assert not result.ok


def test_logout_posts_to_webdisconn(monkeypatch):
    """已认证页面（有离线按钮）才会真的发离线请求。"""
    captured = {}

    def get_handler(url, kwargs):
        if "webdisconnweb.do" in url:
            return FakeResponse(302, headers={"Location": REDIRECT_LOCATION})
        return FakeResponse(200, text=ONLINE_PAGE)

    def post_handler(url, kwargs):
        captured["url"] = url
        captured["data"] = kwargs["data"]
        return FakeResponse(200, text="<html><body>已离线</body></html>")

    install_session(monkeypatch, get_handler, post_handler)
    monkeypatch.setattr(portal, "wait_offline", lambda *a, **k: True)

    result = portal.logout(Config())
    assert result.ok
    assert captured["url"].startswith("https://portal.sicau.edu.cn/webdisconn.do?")
    assert "wlanuserip=10.23.13.100" in captured["url"]
    assert captured["data"]["pageid"] == "201"


def test_logout_short_circuits_when_offline(monkeypatch, login_html):
    sessions = install_session(
        monkeypatch,
        portal_login_page(login_html),
        lambda url, kwargs: pytest.fail("已离线时不应提交"),
    )
    result = portal.logout(Config())
    assert result.ok
    assert "离线" in result.message
    assert len(sessions[0].calls) == 2  # 一次 webdisconnweb.do + 一次取页面


def test_pinned_dns_redirects_and_restores(monkeypatch):
    import socket as socket_module

    seen = {}
    real = socket_module.getaddrinfo

    def fake_getaddrinfo(node, port, *args, **kwargs):
        seen["node"] = node
        return []

    monkeypatch.setattr(socket_module, "getaddrinfo", fake_getaddrinfo)
    with portal.pinned_dns("portal.sicau.edu.cn", "10.255.248.9"):
        socket_module.getaddrinfo("portal.sicau.edu.cn", 443)
        assert seen["node"] == "10.255.248.9"
        socket_module.getaddrinfo("example.com", 443)
        assert seen["node"] == "example.com"
    assert socket_module.getaddrinfo is fake_getaddrinfo
    monkeypatch.setattr(socket_module, "getaddrinfo", real)


def test_login_pins_portal_ip_when_dns_fails(monkeypatch, login_html):
    import contextlib

    used = []

    @contextlib.contextmanager
    def fake_pin(host, ip):
        used.append((host, ip))
        yield

    install_session(
        monkeypatch,
        portal_login_page(login_html),
        lambda url, kwargs: FakeResponse(200, text="<html><body>ok</body></html>"),
    )
    monkeypatch.setattr(portal, "dns_ok", lambda *args, **kwargs: False)
    monkeypatch.setattr(portal, "pinned_dns", fake_pin)
    monkeypatch.setattr(portal, "wait_online", lambda *a, **k: True)

    portal.login(Config(), "202600000", "pw")
    assert used == [("portal.sicau.edu.cn", "10.255.248.9")]


def test_login_does_not_pin_when_dns_works(monkeypatch, login_html):
    used = []
    install_session(
        monkeypatch,
        portal_login_page(login_html),
        lambda url, kwargs: FakeResponse(200, text="<html><body>ok</body></html>"),
    )
    monkeypatch.setattr(portal, "pinned_dns", lambda *a: used.append(a) or None)
    monkeypatch.setattr(portal, "wait_online", lambda *a, **k: True)

    portal.login(Config(), "202600000", "pw")
    assert used == []


def test_check_credentials_mapping(monkeypatch, login_html):
    cases = [("0", True, "正确"), ("3", False, "密码错误"), ("2", False, "帐号不存在")]
    for code, expected_ok, word in cases:
        install_session(
            monkeypatch,
            portal_login_page(login_html),
            lambda url, kwargs, value=code: FakeResponse(200, payload={"check": value}),
        )
        result = portal.check_credentials(Config(), "202600000", "pw")
        assert result.ok is expected_ok
        assert word in result.message



