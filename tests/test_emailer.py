import smtplib
from datetime import date
from decimal import Decimal

import pytest

from utilities_automator.billing import calculate_house_bill
from utilities_automator.config import ConfigError
from utilities_automator.emailer import SmtpSettings, build_message, send_messages

AMOUNTS = {"Gas": Decimal("107.50"), "Electricity": Decimal("18.18"), "Internet": Decimal(45)}


class FakeSMTP:
    def __init__(self, fail_for=()):
        self.sent = []
        self.fail_for = set(fail_for)
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True

    def send_message(self, message):
        if message["To"] in self.fail_for:
            raise smtplib.SMTPRecipientsRefused({message["To"]: (550, b"no")})
        self.sent.append(message)


def test_message_has_breakdown_and_payment_details(house, landlord):
    bill = calculate_house_bill(house, AMOUNTS, date(2026, 11, 1))
    message = build_message(
        bill, bill.tenant_bills[0], landlord, "pat@gmail.com", {"November": "Happy November!"}
    )

    assert message["Subject"] == "November 2026 rent: $1,337.55"
    assert message["To"] == "Upstairs A <a@example.com>"
    assert message["From"] == "Pat <pat@gmail.com>"
    body = message.get_content()
    assert body.startswith("Hi Upstairs A,\n\nHappy November!\n")
    assert "your 22% share" in body
    for line in [
        "Gas: $23.65 (of $107.50)",
        "Electricity: $4.00 (of $18.18)",
        "Internet: $9.90 (of $45.00)",
        "Utilities total: $37.55",
        "Rent: $1,300.00",
        "Total due: $1,337.55",
        "Please e-transfer $1,337.55 to pat@example.com.",
    ]:
        assert line in body
    assert body.rstrip().endswith("Cheers,\nPat")


def test_no_greeting_for_months_without_one(house, landlord):
    bill = calculate_house_bill(house, AMOUNTS, date(2026, 3, 1))
    body = build_message(bill, bill.tenant_bills[0], landlord, "x@gmail.com", {"November": "Hi!"}).get_content()
    assert body.startswith("Hi Upstairs A,\n\nHere is your rent for March 2026")


def test_sends_all_over_one_connection_and_reports_failures(house, landlord):
    bill = calculate_house_bill(house, AMOUNTS, date(2026, 11, 1))
    messages = [build_message(bill, tb, landlord, "pat@gmail.com") for tb in bill.tenant_bills]
    server = FakeSMTP(fail_for={"Master <m@example.com>"})
    settings = SmtpSettings("smtp.example.com", 465, "pat@gmail.com", "secret")

    results = send_messages(messages, settings, connect_fn=lambda s: server)

    assert [m["To"] for m in server.sent] == ["Upstairs A <a@example.com>"]
    assert results[0][1] is None
    assert isinstance(results[1][1], smtplib.SMTPRecipientsRefused)
    assert server.closed


def test_smtp_settings_from_env():
    with pytest.raises(ConfigError, match="EMAIL_APP_PASSWORD"):
        SmtpSettings.from_env({"EMAIL_ADDRESS": "pat@gmail.com"})
    settings = SmtpSettings.from_env({"EMAIL_ADDRESS": "pat@gmail.com", "EMAIL_APP_PASSWORD": "pw"})
    assert (settings.host, settings.port) == ("smtp.gmail.com", 465)
