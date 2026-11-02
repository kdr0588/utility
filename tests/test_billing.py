from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from utilities_automator.billing import (
    calculate_house_bill,
    format_money,
    format_share,
    parse_amount,
)
from utilities_automator.config import Tenant

AMOUNTS = {"Gas": Decimal("107.50"), "Electricity": Decimal("18.18"), "Internet": Decimal("45")}


def test_splits_each_bill_by_share_and_adds_rent(house):
    bill = calculate_house_bill(house, AMOUNTS, date(2026, 11, 15))

    assert bill.month == date(2026, 11, 1)
    assert bill.utilities_total == Decimal("170.68")
    upstairs = bill.tenant_bills[0]
    assert upstairs.utility_shares == {
        "Gas": Decimal("23.65"),
        "Electricity": Decimal("4.00"),
        "Internet": Decimal("9.90"),
    }
    assert upstairs.utilities_total == Decimal("37.55")
    assert upstairs.total_due == Decimal("1337.55")
    assert bill.tenant_bills[1].total_due == Decimal("1537.55")
    assert bill.not_charged == Decimal("170.68") - 2 * Decimal("37.55")


def test_lines_keep_config_order_even_if_amounts_come_in_another_order(house):
    shuffled = dict(reversed(list(AMOUNTS.items())))
    bill = calculate_house_bill(house, shuffled, date(2026, 11, 1))
    assert list(bill.utility_amounts) == ["Gas", "Electricity", "Internet"]


def test_even_split_leftover_cent_is_not_charged(house):
    third = Decimal(1) / 3
    tenants = tuple(
        Tenant(name=n, email=f"{n}@example.com", rent=Decimal(1000), share=third) for n in "abc"
    )
    even_house = replace(house, tenants=tenants)
    bill = calculate_house_bill(
        even_house, {"Gas": Decimal(100), "Electricity": Decimal(0), "Internet": Decimal(0)}, date(2026, 1, 1)
    )
    assert [tb.utilities_total for tb in bill.tenant_bills] == [Decimal("33.33")] * 3
    assert bill.not_charged == Decimal("0.01")


def test_missing_or_unknown_amounts_are_rejected(house):
    with pytest.raises(ValueError, match="missing Internet"):
        calculate_house_bill(house, {"Gas": 1, "Electricity": 1}, date(2026, 1, 1))
    with pytest.raises(ValueError, match="unknown Water"):
        calculate_house_bill(house, {**AMOUNTS, "Water": Decimal(1)}, date(2026, 1, 1))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("107.50", Decimal("107.50")),
        ("$1,070.5", Decimal("1070.5")),
        ("  45 ", Decimal("45")),
        ("-12.00", Decimal("-12.00")),
        ("$-3", Decimal("-3")),
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "12.5.3", "$", "1o7"])
def test_parse_amount_rejects_junk(text):
    with pytest.raises(ValueError):
        parse_amount(text)


def test_formatting():
    assert format_money(Decimal("1337.5")) == "$1,337.50"
    assert format_money(Decimal("-4")) == "-$4.00"
    assert format_share(Decimal("0.22")) == "22%"
    assert format_share(Decimal("0.175")) == "17.5%"
    assert format_share(Decimal(1) / 3) == "33.3%"
