"""Log in to utility websites and read the latest bill amount.

Utility websites change their pages often. When a scraper stops working, run
with --show-browser to watch it, then update the URL or selectors in the
fetch function below. The main script asks you to type the amount whenever a
scraper fails, so a broken scraper never blocks a run.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterator

from .config import Utility

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver

ENBRIDGE_SIGN_IN = "https://myaccount.enbridgegas.com/Sign-In"
ALECTRA_SIGN_IN = "https://myaccount.alectrautilities.com/app/capricorn?para=index"
DEBUG_DIR = Path("debug")

_DOLLAR_AMOUNT = re.compile(r"(-)?\s*\$\s*(-)?\s*(\d[\d,]*(?:\.\d+)?)")


class ScrapeError(RuntimeError):
    """A utility website could not be read."""


def find_dollar_amount(text: str) -> Decimal | None:
    """Return the first $ amount in a piece of page text, or None."""
    match = _DOLLAR_AMOUNT.search(text or "")
    if not match:
        return None
    value = Decimal(match.group(3).replace(",", ""))
    return -value if (match.group(1) or match.group(2)) else value


@contextmanager
def chrome(headless: bool = True) -> Iterator["WebDriver"]:
    """Start Chrome. Selenium downloads the matching driver by itself."""
    from selenium import webdriver

    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1366,900")
    driver = webdriver.Chrome(options=options)
    try:
        yield driver
    finally:
        driver.quit()


def fetch_enbridge(driver: "WebDriver", username: str, password: str, timeout: int) -> Decimal:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    wait = WebDriverWait(driver, timeout)
    driver.get(ENBRIDGE_SIGN_IN)
    wait.until(EC.element_to_be_clickable((By.ID, "signin-username"))).send_keys(username)
    driver.find_element(By.ID, "signin-password").send_keys(password, Keys.RETURN)
    _click_if_present(driver, By.ID, "cancelNotification")

    # The site spells this class "uasge". The second block holds the latest bill.
    def latest_bill(d: "WebDriver"):
        blocks = d.find_elements(By.CSS_SELECTOR, "div.gas-uasge-details")
        if len(blocks) < 2:
            return False
        for bold in blocks[1].find_elements(By.TAG_NAME, "b"):
            amount = find_dollar_amount(bold.text)
            if amount is not None:
                return (amount,)  # wrapped so a $0.00 bill still counts as found
        return False

    return wait.until(latest_bill)[0]


def fetch_alectra(driver: "WebDriver", account: str, password: str, timeout: int) -> Decimal:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    wait = WebDriverWait(driver, timeout)
    driver.get(ALECTRA_SIGN_IN)
    wait.until(EC.element_to_be_clickable((By.ID, "accessEmail"))).send_keys(account)
    driver.find_element(By.ID, "password1").send_keys(password, Keys.RETURN)

    # The first bold dollar amount on the account page is the amount due.
    def amount_due(d: "WebDriver"):
        for strong in d.find_elements(By.TAG_NAME, "strong"):
            amount = find_dollar_amount(strong.text)
            if amount is not None:
                return (amount,)
        return False

    return wait.until(amount_due)[0]


Fetcher = Callable[["WebDriver", str, str, int], Decimal]
FETCHERS: dict[str, Fetcher] = {"enbridge": fetch_enbridge, "alectra": fetch_alectra}


def fetch_amount(
    utility: Utility, *, headless: bool = True, timeout: int = 30, label: str = ""
) -> Decimal:
    """Log in with the utility's credentials from .env and return the bill amount."""
    username, password = utility.credentials()
    fetcher = FETCHERS[utility.source]
    try:
        with chrome(headless) as driver:
            try:
                return fetcher(driver, username, password, timeout)
            except Exception as exc:
                screenshot = _save_screenshot(driver, label or utility.source)
                detail = _describe(exc)
                if screenshot:
                    detail += f" (screenshot saved to {screenshot})"
                raise ScrapeError(detail) from exc
    except ScrapeError:
        raise
    except Exception as exc:
        raise ScrapeError(f"could not start Chrome: {_describe(exc)}") from exc


def _click_if_present(driver: "WebDriver", by: str, value: str, wait_seconds: int = 5) -> None:
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    try:
        WebDriverWait(driver, wait_seconds).until(EC.element_to_be_clickable((by, value))).click()
    except TimeoutException:
        pass


def _save_screenshot(driver: "WebDriver", label: str) -> Path | None:
    try:
        DEBUG_DIR.mkdir(exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_-]+", "-", label).strip("-") or "page"
        path = DEBUG_DIR / f"{safe}-{datetime.now():%Y%m%d-%H%M%S}.png"
        return path if driver.save_screenshot(str(path)) else None
    except Exception:
        return None


def _describe(exc: Exception) -> str:
    # Selenium errors keep the short reason in .msg; str() adds a long stack trace.
    message = getattr(exc, "msg", None)
    if not isinstance(message, str):
        message = str(exc).strip().removeprefix("Message:")
    message = message.strip()
    first_line = message.splitlines()[0].strip() if message else ""
    if not first_line and type(exc).__name__ == "TimeoutException":
        first_line = "the page did not show the bill in time"
    return f"{type(exc).__name__}: {first_line}" if first_line else type(exc).__name__
