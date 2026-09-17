"""门户认证：探测在线状态、发现参数、解析登录表单、登录 / 离线。

实测结论（2026-09，portal.sicau.edu.cn，华为 BRAS）：
  * 在线判定：GET http://connect.rom.miui.com/generate_204 返回 204。
  * 未认证时该请求会被 BRAS 拦成 302，Location 里带 wlanuserip/wlanacname/nasip。
  * 认证入口：/webdisconnweb.do -> 302 /index_auth.jsp?... -> /webauth.do?<urlParameter>
  * 登录：POST /webauth.do?<urlParameter>，提交页面里 #goLoginForm 内的字段。
  * 离线：POST /webdisconn.do?<urlParameter>，字段同上。

登录表单不做硬编码：直接解析页面里 #goLoginForm 的字段，
门户改版后依然可用。
"""

from __future__ import annotations

import contextlib
import functools
import json
import logging
import re
import socket
import threading
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode

import requests

from . import wifi
from .config import Config

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 8.0
ONLINE_STATUS = 204
REDIRECT_STATUS = (301, 302, 303, 307, 308)

# 响应里出现这些词说明认证被拒，原样回报给用户
ERROR_KEYWORDS = (
    "密码错误",
    "帐号不存在",
    "账号不存在",
    "用户名或密码",
    "认证失败",
    "登录失败",
    "验证失败",
    "帐号已停用",
    "账号已停用",
    "用户被锁定",
    "余额不足",
    "已欠费",
    "不在认证",
)

_SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_ERR_MESSAGE_RE = re.compile(r'id="errMessage"[^>]*value="([^"]*)"')
# 实测：未认证页面有 <button id="submitForm">（登录），
# 已认证页面有 <button id="online">（离线）。用按钮区分比看表单字段可靠。
_LOGIN_BUTTON_RE = re.compile(r'<button[^>]*id="submitForm"', re.I)
_LOGOUT_BUTTON_RE = re.compile(r'<button[^>]*id="online"', re.I)


@dataclass
class Result:
    ok: bool
    message: str
    detail: str = ""

    def __bool__(self) -> bool:
        return self.ok


@dataclass
class ProbeResult:
    online: bool
    params: dict = field(default_factory=dict)
    detail: str = ""


@dataclass
class LoginForm:
    action: str = ""
    fields: dict = field(default_factory=dict)
    url_parameter: str = ""

    @property
    def is_login_form(self) -> bool:
        """带 userId 输入框才是真正的登录页。"""
        return "userId" in self.fields


class _FormParser(HTMLParser):
    """只收集 id=goLoginForm 这个表单里可提交的字段。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found = False
        self.action = ""
        self.fields: dict = {}
        self.url_parameter = ""
        self._inside = False
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        attributes = {key.lower(): (value or "") for key, value in attrs}
        if tag == "form":
            if self._inside:
                self._depth += 1
            elif attributes.get("id") == "goLoginForm":
                self._inside = True
                self.found = True
                self.action = attributes.get("action", "")
            return
        if not self._inside or tag != "input":
            return
        # urlParameter 本身是 disabled，但 JS 用它拼提交地址，需要单独取出
        if attributes.get("id") == "urlParameter":
            self.url_parameter = attributes.get("value", "")
        name = attributes.get("name", "")
        if not name or "disabled" in attributes:
            return
        self.fields[name] = attributes.get("value", "")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag != "form" or not self._inside:
            return
        if self._depth:
            self._depth -= 1
        else:
            self._inside = False


def parse_login_form(html: str) -> LoginForm | None:
    parser = _FormParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # 门户偶尔会返回截断的 HTML
        log.debug("解析登录表单失败：%s", exc)
        return None
    if not parser.found:
        return None
    return LoginForm(
        action=parser.action,
        fields=parser.fields,
        url_parameter=parser.url_parameter,
    )


def params_from_url(url: str) -> dict:
    """从 URL（或 Location 头）里取查询参数。"""
    if not url:
        return {}
    query = url.split("?", 1)[1] if "?" in url else url
    query = query.split("#", 1)[0]
    params = {}
    for key, value in parse_qsl(query, keep_blank_values=True):
        params[key] = value
    return params


def visible_text(html: str) -> str:
    text = _SCRIPT_RE.sub(" ", html)
    text = _TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_error(html: str) -> str:
    """从响应里提取错误提示，没有则返回空串。"""
    match = _ERR_MESSAGE_RE.search(html)
    if match and match.group(1).strip():
        return match.group(1).strip()
    text = visible_text(html)
    for keyword in ERROR_KEYWORDS:
        index = text.find(keyword)
        if index >= 0:
            return text[max(0, index - 24): index + 60].strip()
    return ""


def page_state(html: str) -> str:
    """判断门户页面状态：login（未认证）/ online（已认证）/ unknown。"""
    if _LOGIN_BUTTON_RE.search(html):
        return "login"
    if _LOGOUT_BUTTON_RE.search(html):
        return "online"
    return "unknown"


def _browser_headers(referer: str | None = None) -> dict:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    return headers


_dns_lock = threading.Lock()


def dns_ok(host: str) -> bool:
    try:
        socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        return True
    except (socket.gaierror, OSError):
        return False


@contextlib.contextmanager
def pinned_dns(host: str, ip: str):
    """把 host 的域名解析临时指到 ip。

    只改 TCP 连接用的地址；TLS 的 SNI 和 HTTP 的 Host 头仍然是原域名，
    所以证书校验照常通过。
    """
    with _dns_lock:
        original = socket.getaddrinfo

        def patched(node, port, *args, **kwargs):
            if node == host:
                node = ip
            return original(node, port, *args, **kwargs)

        socket.getaddrinfo = patched
        try:
            yield
        finally:
            socket.getaddrinfo = original


def with_dns_fallback(func):
    """域名解析不了时，用配置里的 portal_ip 直连兜底。"""

    @functools.wraps(func)
    def wrapper(cfg: Config, *args, **kwargs):
        if cfg.portal_ip and not dns_ok(cfg.portal_host):
            log.warning("解析不了 %s，改用直连 %s", cfg.portal_host, cfg.portal_ip)
            with pinned_dns(cfg.portal_host, cfg.portal_ip):
                return func(cfg, *args, **kwargs)
        return func(cfg, *args, **kwargs)

    return wrapper


def probe(cfg: Config, timeout: float = DEFAULT_TIMEOUT) -> ProbeResult:
    """探测是否已联网；未联网时尽量顺带拿到认证参数。"""
    try:
        response = requests.get(
            cfg.probe_url,
            timeout=timeout,
            allow_redirects=False,
            headers=_browser_headers(),
        )
    except requests.RequestException as exc:
        return ProbeResult(False, {}, "%s: %s" % (type(exc).__name__, exc))

    if response.status_code == ONLINE_STATUS:
        return ProbeResult(True, {}, "HTTP 204")

    if response.status_code in REDIRECT_STATUS:
        location = response.headers.get("Location", "")
        params = params_from_url(location)
        detail = "HTTP %d -> %s" % (response.status_code, location[:160])
        return ProbeResult(False, params if "wlanuserip" in params else {}, detail)

    return ProbeResult(False, {}, "HTTP %d" % response.status_code)


def login_page_url(cfg: Config, params: dict | None = None) -> str:
    base = cfg.base_url + "/webauth.do"
    if params:
        return base + "?" + urlencode(params)
    return base


def discover_params(
    session: requests.Session,
    cfg: Config,
    seed: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple:
    """三级兜底获取认证参数，返回 (params, 来源说明)。"""
    if seed and "wlanuserip" in seed:
        return dict(seed), "探测重定向"

    try:
        response = session.get(
            cfg.base_url + "/webdisconnweb.do",
            timeout=timeout,
            allow_redirects=False,
            headers=_browser_headers(),
        )
        location = response.headers.get("Location", "")
        params = params_from_url(location)
        if "wlanuserip" in params:
            return params, "门户 302"
    except requests.RequestException as exc:
        log.debug("webdisconnweb.do 失败：%s", exc)

    # 最后兜底：本地拼装
    address = wifi.local_ipv4()
    params = {}
    if address:
        params["wlanacip"] = address
        params["wlanuserip"] = address
    if cfg.ac_name:
        params["wlanacname"] = cfg.ac_name
    return params, "本地拼装"


def wait_online(
    cfg: Config, timeout: float = DEFAULT_TIMEOUT, attempts: int = 4, delay: float = 1.5
) -> bool:
    for index in range(attempts):
        if probe(cfg, timeout=timeout).online:
            return True
        if index < attempts - 1:
            time.sleep(delay)
    return False


def wait_offline(
    cfg: Config, timeout: float = DEFAULT_TIMEOUT, attempts: int = 4, delay: float = 1.0
) -> bool:
    for index in range(attempts):
        if not probe(cfg, timeout=timeout).online:
            return True
        if index < attempts - 1:
            time.sleep(delay)
    return False


def _fetch_login_page(session, cfg, params, timeout):
    seed, source = discover_params(session, cfg, seed=params, timeout=timeout)
    url = login_page_url(cfg, seed)
    log.info("打开认证页（参数来源：%s）：%s", source, url)
    response = session.get(
        url, timeout=timeout, headers=_browser_headers(cfg.base_url + "/")
    )
    return seed, url, response


def build_login_payload(form: LoginForm, username: str, password: str) -> dict:
    """把页面上的字段原样带上，再覆盖账号密码。

    表单里 disabled 的字段不会提交，isRemind 固定为 0，
    免得门户侧替我们"记住密码"。
    """
    payload = dict(form.fields)
    payload["userId"] = username
    payload["passwd"] = password
    payload["isRemind"] = "0"
    return payload


def submit_query(form: LoginForm, seed: dict) -> str:
    """浏览器就是拿页面里的 urlParameter 拼提交地址的。"""
    return form.url_parameter or urlencode(seed)


@with_dns_fallback
def login(
    cfg: Config,
    username: str,
    password: str,
    params: dict | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Result:
    if not username or not password:
        return Result(False, "未配置学号或密码")

    session = requests.Session()
    try:
        seed, url, response = _fetch_login_page(session, cfg, params, timeout)
        form = parse_login_form(response.text)
        if form is None:
            return Result(
                False,
                "认证页里没找到登录表单（门户可能改版）",
                visible_text(response.text)[:300],
            )
        state = page_state(response.text)
        if state == "online":
            return Result(True, "门户显示当前已在线，无需重复认证")
        if not form.is_login_form:
            return Result(False, "认证页里没找到账号密码输入框")

        payload = build_login_payload(form, username, password)
        post_url = cfg.base_url + "/webauth.do?" + submit_query(form, seed)
        log.info("提交认证：user=%s 字段数=%d", username, len(payload))
        posted = session.post(
            post_url,
            data=payload,
            timeout=timeout,
            allow_redirects=True,
            headers=_browser_headers(url),
        )
        message = extract_error(posted.text)
        if message:
            return Result(False, message, visible_text(posted.text)[:300])
        if wait_online(cfg, timeout=timeout):
            return Result(True, "认证成功")
        return Result(
            False,
            "已提交认证但探测仍未联网，请查看日志",
            visible_text(posted.text)[:300],
        )
    except requests.RequestException as exc:
        return Result(False, "网络请求失败：%s" % exc)
    finally:
        session.close()


@with_dns_fallback
def logout(cfg: Config, timeout: float = DEFAULT_TIMEOUT) -> Result:
    session = requests.Session()
    try:
        seed, url, response = _fetch_login_page(session, cfg, None, timeout)
        form = parse_login_form(response.text)
        if form is None:
            return Result(False, "认证页里没找到表单，无法离线", visible_text(response.text)[:300])
        if page_state(response.text) == "login":
            return Result(True, "当前已经是离线状态")

        post_url = cfg.base_url + "/webdisconn.do?" + submit_query(form, seed)
        log.info("提交离线请求：%s", post_url[:160])
        session.post(
            post_url,
            data=dict(form.fields),
            timeout=timeout,
            allow_redirects=True,
            headers=_browser_headers(url),
        )
        if wait_offline(cfg, timeout=timeout):
            return Result(True, "已离线")
        return Result(False, "离线请求已发送，但探测仍显示在线")
    except requests.RequestException as exc:
        return Result(False, "网络请求失败：%s" % exc)
    finally:
        session.close()


@with_dns_fallback
def check_credentials(
    cfg: Config, username: str, password: str, timeout: float = DEFAULT_TIMEOUT
) -> Result:
    """只校验学号密码，不做认证（门户自己的校验接口）。"""
    if not username or not password:
        return Result(False, "请先填写学号和密码")

    session = requests.Session()
    try:
        _, url, _ = _fetch_login_page(session, cfg, None, timeout)
        response = session.post(
            cfg.base_url + "/httpservice/checkUserPwdGeneral.do",
            data={"userId": username, "passwd": password, "pageid": "201"},
            timeout=timeout,
            headers=_browser_headers(url),
        )
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        return Result(False, "校验请求失败：%s" % exc)
    finally:
        session.close()

    code = str(data.get("check", ""))
    mapping = {
        "0": (True, "学号密码正确"),
        "1": (False, "验证失败"),
        "2": (False, "帐号不存在"),
        "3": (False, "密码错误"),
    }
    ok, message = mapping.get(code, (False, "未知返回：%s" % code))
    return Result(ok, message, json.dumps(data, ensure_ascii=False)[:200])


