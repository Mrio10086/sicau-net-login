import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

FIXTURES = ROOT / "tests" / "fixtures"


@pytest.fixture(scope="session")
def fixtures_dir() -> pathlib.Path:
    return FIXTURES


@pytest.fixture(scope="session")
def login_html() -> str:
    return (FIXTURES / "webauth_preauth.html").read_text(encoding="utf-8")
