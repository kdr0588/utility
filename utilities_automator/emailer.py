"""Write and send the monthly rent email to each tenant."""

from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from typing import Callable, Mapping, Sequence

from .billing import HouseBill, TenantBill, format_money, format_share
from .config import ConfigError, Landlord


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    username: str
    password: str

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "SmtpSettings":
        env = os.environ if environ is None else environ
        missing = [key for key in ("EMAIL_ADDRESS", "EMAIL_APP_PASSWORD") if not env.get(key)]
        if missing:
            raise ConfigError(f"Set {' and '.join(missing)} in your .env file to send emails")
        try:
            port = int(env.get("SMTP_PORT") or 465)
        except ValueError:
            raise ConfigError(f"SMTP_PORT must be a number, got '{env['SMTP_PORT']}'") from None
        return cls(
            host=env.get("SMTP_HOST") or "smtp.gmail.com",
            port=port,
            username=env["EMAIL_ADDRESS"],
            password=env["EMAIL_APP_PASSWORD"],
        )


def email_body(
    house_bill: HouseBill, tenant_bill: TenantBill, landlord: Landlord, greeting: str = ""
) -> str:
    tenant = tenant_bill.tenant
    month = house_bill.month.strftime("%B %Y")
    total = format_money(tenant_bill.total_due)

    lines = [f"Hi {tenant.name},", ""]
    if greeting:
        lines += [greeting, ""]
    lines += [
        f"Here is your rent for {month} at {house_bill.house.name}, plus your "
        f"{format_share(tenant.share)} share of last month's utilities.",
        "",
    ]
    for name, share in tenant_bill.utility_shares.items():
        bill = format_money(house_bill.utility_amounts[name])
        lines.append(f"{name}: {format_money(share)} (of {bill})")
    lines += [
        f"Utilities total: {format_money(tenant_bill.utilities_total)}",
        "",
        f"Rent: {format_money(tenant_bill.rent)}",
        f"Total due: {total}",
        "",
        f"Please e-transfer {total} to {landlord.etransfer_email}.",
        "",
        "Let me know if you have any questions.",
        "",
        "Cheers,",
        landlord.name,
    ]
    return "\n".join(lines) + "\n"


def build_message(
    house_bill: HouseBill,
    tenant_bill: TenantBill,
    landlord: Landlord,
    sender: str,
    greetings: Mapping[str, str] | None = None,
) -> EmailMessage:
    greeting = (greetings or {}).get(house_bill.month.strftime("%B"), "")
    message = EmailMessage()
    message["Subject"] = (
        f"{house_bill.month:%B %Y} rent: {format_money(tenant_bill.total_due)}"
    )
    message["From"] = formataddr((landlord.name, sender))
    message["To"] = formataddr((tenant_bill.tenant.name, tenant_bill.tenant.email))
    message.set_content(email_body(house_bill, tenant_bill, landlord, greeting))
    return message


def connect(settings: SmtpSettings) -> smtplib.SMTP:
    context = ssl.create_default_context()
    if settings.port == 465:
        server: smtplib.SMTP = smtplib.SMTP_SSL(
            settings.host, settings.port, context=context, timeout=30
        )
    else:
        server = smtplib.SMTP(settings.host, settings.port, timeout=30)
        server.starttls(context=context)
    server.login(settings.username, settings.password)
    return server


def send_messages(
    messages: Sequence[EmailMessage],
    settings: SmtpSettings,
    *,
    connect_fn: Callable[[SmtpSettings], smtplib.SMTP] = connect,
) -> list[tuple[EmailMessage, Exception | None]]:
    """Send every message over one connection. Returns each message with its error, if any."""
    results: list[tuple[EmailMessage, Exception | None]] = []
    if not messages:
        return results
    with connect_fn(settings) as server:
        for message in messages:
            try:
                server.send_message(message)
            except smtplib.SMTPException as exc:
                results.append((message, exc))
            else:
                results.append((message, None))
    return results
