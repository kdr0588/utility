from contextlib import contextmanager
from decimal import Decimal

import pytest

from utilities_automator import scrapers
from utilities_automator.config import Utility
from utilities_automator.scrapers import ScrapeError, fetch_amount, find_dollar_amount


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Amount due: $1,234.56", Decimal("1234.56")),
        ("Bill 2 of 3 $107.50 due Nov 20", Decimal("107.50")),
        ("Credit -$12.00", Decimal("-12.00")),
        ("$0.00", Decimal("0.00")),
        ("No amount here", None),
    ],
)
def test_find_dollar_amount(text, expected):
    assert find_dollar_amount(text) == expected


class FakeDriver:
    def save_screenshot(self, path):
        return False


@pytest.fixture
def gas(monkeypatch):
    monkeypatch.setenv("GAS_USER", "me")
    monkeypatch.setenv("GAS_PASS", "pw")
    return Utility(name="Gas", source="enbridge", username_env="GAS_USER", password_env="GAS_PASS")


@pytest.fixture
def fake_chrome(monkeypatch, tmp_path):
    monkeypatch.setattr(scrapers, "DEBUG_DIR", tmp_path / "debug")

    @contextmanager
    def chrome(headless=True):
        yield FakeDriver()

    monkeypatch.setattr(scrapers, "chrome", chrome)


def test_fetch_amount_uses_credentials(gas, fake_chrome, monkeypatch):
    seen = {}

    def fetcher(driver, username, password, timeout):
        seen.update(username=username, password=password)
        return Decimal("88.10")

    monkeypatch.setitem(scrapers.FETCHERS, "enbridge", fetcher)
    assert fetch_amount(gas) == Decimal("88.10")
    assert seen == {"username": "me", "password": "pw"}


def test_page_errors_become_scrape_errors(gas, fake_chrome, monkeypatch):
    def broken(driver, username, password, timeout):
        raise LookupError("Message: no such element: signin-username\n  stack...")

    monkeypatch.setitem(scrapers.FETCHERS, "enbridge", broken)
    with pytest.raises(ScrapeError, match="LookupError: no such element: signin-username$"):
        fetch_amount(gas)


def test_browser_start_failure_becomes_scrape_error(gas, monkeypatch):
    @contextmanager
    def no_chrome(headless=True):
        raise OSError("chrome not found")
        yield

    monkeypatch.setattr(scrapers, "chrome", no_chrome)
    with pytest.raises(ScrapeError, match="could not start Chrome: OSError: chrome not found"):
        fetch_amount(gas)
