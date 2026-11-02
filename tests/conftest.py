from decimal import Decimal

import pytest

from utilities_automator.config import House, Landlord, Tenant, Utility


@pytest.fixture
def landlord():
    return Landlord(name="Pat", etransfer_email="pat@example.com")


@pytest.fixture
def house():
    return House(
        id="58",
        name="58 House",
        utilities=(
            Utility(name="Gas", source="manual"),
            Utility(name="Electricity", source="manual"),
            Utility(name="Internet", source="fixed", amount=Decimal("45")),
        ),
        tenants=(
            Tenant(name="Upstairs A", email="a@example.com", rent=Decimal(1300), share=Decimal("0.22")),
            Tenant(name="Master", email="m@example.com", rent=Decimal(1500), share=Decimal("0.22")),
        ),
    )


SETTINGS = """
workbook = "bills.xlsx"

[landlord]
name = "Pat"
etransfer_email = "pat@example.com"

[greetings]
november = "Happy November!"

[[houses]]
id = "58"
name = "58 House"

[[houses.utilities]]
name = "Gas"
source = "enbridge"
username_env = "H58_GAS_USER"
password_env = "H58_GAS_PASS"

[[houses.utilities]]
name = "Internet"
source = "fixed"
amount = 45.00

[[houses.tenants]]
name = "Upstairs A"
email = "a@example.com"
rent = 1300
share = 0.22

[[houses.tenants]]
name = "Master"
email = "m@example.com"
rent = 1500
share = 0.22

[[houses]]
id = "23"
name = "23 House"

[[houses.utilities]]
name = "Gas"
source = "manual"

[[houses.tenants]]
name = "Downstairs A"
email = "d@example.com"
rent = 1350
"""


@pytest.fixture
def settings_file(tmp_path):
    path = tmp_path / "houses.toml"
    path.write_text(SETTINGS, encoding="utf-8")
    return path
