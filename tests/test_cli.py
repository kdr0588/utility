from datetime import date
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from utilities_automator.cli import main
from utilities_automator.scrapers import ScrapeError

from .test_emailer import FakeSMTP

TODAY = date(2026, 11, 2)


class Answers:
    """Stands in for input(): returns the scripted answer for the first matching prompt text."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        for i, (needle, answer) in enumerate(self.answers):
            if needle in prompt:
                del self.answers[i]
                return answer
        raise AssertionError(f"Unexpected prompt: {prompt!r}")


@pytest.fixture
def env(monkeypatch, tmp_path):
    for key in ("EMAIL_ADDRESS", "EMAIL_APP_PASSWORD", "H58_GAS_USER", "H58_GAS_PASS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("EMAIL_ADDRESS", "pat@gmail.com")
    monkeypatch.setenv("EMAIL_APP_PASSWORD", "app-pw")
    return ["--env-file", str(tmp_path / "missing.env")]


def scraped(amount):
    def fetch(utility, **kwargs):
        return Decimal(amount)

    return fetch


def test_dry_run_saves_and_sends_nothing(settings_file, env, capsys):
    ask = Answers([("23 House Gas", "60")])
    code = main(["--config", str(settings_file), "--dry-run", *env], ask=ask, fetch=scraped("100"), today=TODAY)

    out = capsys.readouterr().out
    assert code == 0
    assert not (settings_file.parent / "bills.xlsx").exists()
    assert "Upstairs A: $31.90 utilities + $1,300.00 rent = $1,331.90" in out
    assert "Downstairs A: $60.00 utilities + $1,350.00 rent = $1,410.00" in out
    assert "Subject: November 2026 rent: $1,331.90" in out
    assert "Dry run: nothing was saved or sent." in out


def test_full_run_saves_then_asks_before_each_email(settings_file, env, capsys):
    server = FakeSMTP()
    ask = Answers([
        ("23 House Gas", "oops"),
        ("23 House Gas", "$60"),
        ("Email Upstairs A", "y"),
        ("Email Master", "n"),
        ("Email Downstairs A", "yes"),
    ])
    code = main(
        ["--config", str(settings_file), *env],
        ask=ask, fetch=scraped("100"), connect_fn=lambda s: server, today=TODAY,
    )

    assert code == 0
    assert [m["To"] for m in server.sent] == ["Upstairs A <a@example.com>", "Downstairs A <d@example.com>"]
    assert server.sent[0]["From"] == "Pat <pat@gmail.com>"
    assert "'oops' is not a dollar amount" in capsys.readouterr().out
    workbook = load_workbook(settings_file.parent / "bills.xlsx")
    assert workbook.sheetnames == ["58 House", "23 House"]


def test_scrape_failure_falls_back_to_typing_the_amount(settings_file, env, capsys):
    def broken(utility, **kwargs):
        raise ScrapeError("TimeoutException: the page did not show the bill in time")

    ask = Answers([("58 House Gas", "107.50")])
    code = main(
        ["--config", str(settings_file), "--house", "58", "--no-email", *env],
        ask=ask, fetch=broken, today=TODAY,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "Could not read Gas automatically: TimeoutException" in out
    assert "Upstairs A: $33.55 utilities" in out
    assert load_workbook(settings_file.parent / "bills.xlsx").sheetnames == ["58 House"]


def test_manual_flag_skips_the_websites(settings_file, env):
    def never(utility, **kwargs):
        raise AssertionError("should not scrape with --manual")

    ask = Answers([("58 House Gas", "10")])
    code = main(
        ["--config", str(settings_file), "--house", "58", "--manual", "--dry-run", *env],
        ask=ask, fetch=never, today=TODAY,
    )
    assert code == 0


def test_yes_sends_everything_for_the_chosen_month(settings_file, env):
    server = FakeSMTP()
    code = main(
        ["--config", str(settings_file), "--house", "58", "--month", "2026-12", "--yes", *env],
        ask=Answers([]), fetch=scraped("100"), connect_fn=lambda s: server, today=TODAY,
    )
    assert code == 0
    assert [m["Subject"] for m in server.sent] == [
        "December 2026 rent: $1,331.90",
        "December 2026 rent: $1,531.90",
    ]


def test_missing_email_password_stops_before_any_work(settings_file, env, monkeypatch, capsys):
    monkeypatch.delenv("EMAIL_APP_PASSWORD")
    code = main(["--config", str(settings_file), *env], ask=Answers([]), fetch=scraped("1"), today=TODAY)
    assert code == 2
    assert "EMAIL_APP_PASSWORD" in capsys.readouterr().err


def test_unknown_house_is_a_settings_problem(settings_file, env, capsys):
    code = main(["--config", str(settings_file), "--house", "99", *env], ask=Answers([]), today=TODAY)
    assert code == 2
    assert "No house with id '99'" in capsys.readouterr().err


def test_failed_email_returns_error_code(settings_file, env, capsys):
    server = FakeSMTP(fail_for={"Master <m@example.com>"})
    code = main(
        ["--config", str(settings_file), "--house", "58", "--yes", *env],
        ask=Answers([]), fetch=scraped("100"), connect_fn=lambda s: server, today=TODAY,
    )
    assert code == 1
    assert "FAILED to send to Master <m@example.com>" in capsys.readouterr().err
