"""Command line entry point: python -m utilities_automator"""

from __future__ import annotations

import argparse
import smtplib
import sys
from datetime import date
from decimal import Decimal
from email.message import EmailMessage
from typing import Callable, Sequence

from dotenv import load_dotenv

from . import scrapers
from .billing import HouseBill, calculate_house_bill, format_money, parse_amount
from .config import Config, ConfigError, House, Utility, load_config
from .emailer import SmtpSettings, build_message, connect, send_messages
from .scrapers import ScrapeError
from .spreadsheet import record_bills

Ask = Callable[[str], str]
Fetch = Callable[..., Decimal]


def parse_month(text: str) -> date:
    try:
        year, month = (int(part) for part in text.split("-"))
        return date(year, month, 1)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{text}' is not a month like 2026-11") from None


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m utilities_automator",
        description=(
            "Collect each house's utility bills, split them between the tenants, "
            "log them in a spreadsheet and email every tenant what they owe."
        ),
    )
    parser.add_argument("--config", default="houses.toml", help="settings file (default: houses.toml)")
    parser.add_argument("--env-file", default=".env", help="passwords file (default: .env)")
    parser.add_argument(
        "--house",
        action="append",
        metavar="ID",
        help="only run this house; repeat for more than one (default: every house)",
    )
    parser.add_argument(
        "--month", type=parse_month, metavar="YYYY-MM", help="rent month (default: this month)"
    )
    parser.add_argument(
        "--manual",
        action="store_true",
        help="type in every bill amount instead of logging in to the utility websites",
    )
    parser.add_argument(
        "--show-browser", action="store_true", help="show Chrome while it logs in (for fixing scrapers)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="show the breakdowns and emails without saving or sending"
    )
    parser.add_argument("--no-email", action="store_true", help="save to the spreadsheet but send no emails")
    parser.add_argument("--yes", action="store_true", help="send every email without asking first")
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    *,
    ask: Ask = input,
    fetch: Fetch | None = None,
    connect_fn: Callable[[SmtpSettings], smtplib.SMTP] = connect,
    today: date | None = None,
) -> int:
    args = parse_args(argv)
    load_dotenv(args.env_file)
    fetch = fetch or scrapers.fetch_amount
    month = args.month or (today or date.today()).replace(day=1)
    sending = not (args.dry_run or args.no_email)

    try:
        config = load_config(args.config)
        houses = [config.house(house_id) for house_id in args.house] if args.house else list(config.houses)
        smtp = SmtpSettings.from_env() if sending else None
    except ConfigError as exc:
        print(f"Settings problem: {exc}", file=sys.stderr)
        return 2

    try:
        bills = [collect_house_bill(house, month, args, ask, fetch) for house in houses]

        if args.dry_run:
            show_emails(bills, config)
            print("\nDry run: nothing was saved or sent.")
            return 0

        record_bills(config.workbook, bills)
        print(f"\nSaved {month:%B %Y} to {config.workbook}")

        if not sending:
            return 0
        messages = choose_emails(bills, config, smtp.username, ask, send_all=args.yes)
    except PermissionError as exc:
        print(exc, file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nStopped.", file=sys.stderr)
        return 130

    if not messages:
        print("No emails sent.")
        return 0
    try:
        results = send_messages(messages, smtp, connect_fn=connect_fn)
    except (smtplib.SMTPException, OSError) as exc:
        print(f"Could not connect to the email server: {exc}", file=sys.stderr)
        return 1

    failed = 0
    for message, error in results:
        if error is None:
            print(f"Sent to {message['To']}")
        else:
            failed += 1
            print(f"FAILED to send to {message['To']}: {error}", file=sys.stderr)
    return 1 if failed else 0


def collect_house_bill(
    house: House, month: date, args: argparse.Namespace, ask: Ask, fetch: Fetch
) -> HouseBill:
    print(f"\n== {house.name} ==")
    amounts = {u.name: get_amount(house, u, args, ask, fetch) for u in house.utilities}
    bill = calculate_house_bill(house, amounts, month)
    print_summary(bill)
    return bill


def get_amount(
    house: House, utility: Utility, args: argparse.Namespace, ask: Ask, fetch: Fetch
) -> Decimal:
    if utility.source == "fixed":
        print(f"  {utility.name}: {format_money(utility.amount)} (fixed)")
        return utility.amount

    if utility.is_scraped and not args.manual:
        print(f"  {utility.name}: logging in to {utility.source.title()}...", flush=True)
        try:
            amount = fetch(
                utility, headless=not args.show_browser, label=f"{house.id}-{utility.name}"
            )
        except (ScrapeError, ConfigError) as exc:
            print(f"  Could not read {utility.name} automatically: {exc}")
        else:
            print(f"  {utility.name}: {format_money(amount)}")
            return amount

    return ask_amount(f"  Enter the {house.name} {utility.name} bill: $", ask)


def ask_amount(prompt: str, ask: Ask) -> Decimal:
    while True:
        try:
            return parse_amount(ask(prompt))
        except ValueError as exc:
            print(f"  {exc}. Try again, for example 107.50")


def print_summary(bill: HouseBill) -> None:
    print(f"  Utilities total: {format_money(bill.utilities_total)}")
    for tenant_bill in bill.tenant_bills:
        print(
            f"  {tenant_bill.tenant.name}: {format_money(tenant_bill.utilities_total)} utilities"
            f" + {format_money(tenant_bill.rent)} rent = {format_money(tenant_bill.total_due)}"
        )
    if bill.not_charged:
        print(f"  Not charged to tenants: {format_money(bill.not_charged)}")


def show_emails(bills: Sequence[HouseBill], config: Config) -> None:
    for bill in bills:
        for tenant_bill in bill.tenant_bills:
            message = build_message(
                bill, tenant_bill, config.landlord, "you@example.com", config.greetings
            )
            print(f"\n--- To: {message['To']}\n--- Subject: {message['Subject']}\n")
            print(message.get_content().rstrip())


def choose_emails(
    bills: Sequence[HouseBill], config: Config, sender: str, ask: Ask, *, send_all: bool
) -> list[EmailMessage]:
    chosen = []
    if not send_all:
        print()
    for bill in bills:
        for tenant_bill in bill.tenant_bills:
            tenant = tenant_bill.tenant
            question = (
                f"Email {tenant.name} <{tenant.email}> "
                f"{format_money(tenant_bill.total_due)}? [y/N] "
            )
            if send_all or ask(question).strip().lower() in {"y", "yes"}:
                chosen.append(
                    build_message(bill, tenant_bill, config.landlord, sender, config.greetings)
                )
    return chosen
