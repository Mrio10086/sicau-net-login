import sys

import pytest

from sicau_net import credentials

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="DPAPI 只在 Windows 上可用"
)


def test_protect_roundtrip():
    secret = "这是密码-p@ssw0rd".encode("utf-8")
    blob = credentials.protect(secret)
    assert blob != secret
    assert credentials.unprotect(blob) == secret


def test_save_load_clear(tmp_path):
    path = tmp_path / "cred.dat"
    credentials.save_credentials("202600000", "p@ssw0rd", path=path)
    assert path.exists()
    assert credentials.has_credentials(path)

    loaded = credentials.load_credentials(path)
    assert loaded is not None
    assert loaded.username == "202600000"
    assert loaded.password == "p@ssw0rd"

    assert credentials.clear_credentials(path) is True
    assert credentials.load_credentials(path) is None


def test_load_returns_none_for_garbage(tmp_path):
    path = tmp_path / "cred.dat"
    path.write_bytes(b"not-an-encrypted-blob")
    assert credentials.load_credentials(path) is None


def test_missing_file(tmp_path):
    assert credentials.load_credentials(tmp_path / "nope.dat") is None
    assert credentials.clear_credentials(tmp_path / "nope.dat") is False
