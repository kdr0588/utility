"""Split each house's utility bills between its tenants."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Mapping

from .config import House, Tenant

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
_TYPED_AMOUNT = re.compile(r"^\s*(-)?\s*\$?\s*(-)?\s*(\d[\d,]*(?:\.\d+)?)\s*$")


def money(value: Decimal | int | str) -> Decimal:
    """Round to the nearest cent."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def format_money(value: Decimal) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def format_share(share: Decimal) -> str:
    text = f"{share * 100:.1f}".rstrip("0").rstrip(".")
    return f"{text}%"


def parse_amount(text: str) -> Decimal:
    """Read a typed amount such as '107.50', '$1,070.5' or '-12'."""
    match = _TYPED_AMOUNT.match(text or "")
    if not match:
        raise ValueError(f"'{text.strip()}' is not a dollar amount")
    try:
        value = Decimal(match.group(3).replace(",", ""))
    except InvalidOperation:
        raise ValueError(f"'{text.strip()}' is not a dollar amount") from None
    return -value if (match.group(1) or match.group(2)) else value


@dataclass(frozen=True)
class TenantBill:
    tenant: Tenant
    utility_shares: Mapping[str, Decimal]

    @property
    def utilities_total(self) -> Decimal:
        return sum(self.utility_shares.values(), ZERO)

    @property
    def rent(self) -> Decimal:
        return money(self.tenant.rent)

    @property
    def total_due(self) -> Decimal:
        return self.rent + self.utilities_total


@dataclass(frozen=True)
class HouseBill:
    house: House
    month: date
    utility_amounts: Mapping[str, Decimal]
    tenant_bills: tuple[TenantBill, ...]

    @property
    def utilities_total(self) -> Decimal:
        return sum(self.utility_amounts.values(), ZERO)

    @property
    def not_charged(self) -> Decimal:
        """The part of the bills no tenant pays (the landlord's share or rounding)."""
        charged = sum((tb.utilities_total for tb in self.tenant_bills), ZERO)
        return self.utilities_total - charged


def calculate_house_bill(
    house: House, amounts: Mapping[str, Decimal], month: date
) -> HouseBill:
    """Work out each tenant's share of every bill, rounded to the cent.

    Each line is rounded on its own and the tenant's utilities total is the sum
    of those rounded lines, so the numbers in the email always add up.
    """
    expected = [u.name for u in house.utilities]
    missing = [name for name in expected if name not in amounts]
    unknown = [name for name in amounts if name not in expected]
    if missing or unknown:
        problems = []
        if missing:
            problems.append(f"missing {', '.join(missing)}")
        if unknown:
            problems.append(f"unknown {', '.join(unknown)}")
        raise ValueError(f"{house.name}: bill amounts {'; '.join(problems)}")

    ordered = {name: money(amounts[name]) for name in expected}
    tenant_bills = tuple(
        TenantBill(
            tenant=tenant,
            utility_shares={name: money(amount * tenant.share) for name, amount in ordered.items()},
        )
        for tenant in house.tenants
    )
    return HouseBill(
        house=house,
        month=month.replace(day=1),
        utility_amounts=ordered,
        tenant_bills=tenant_bills,
    )
