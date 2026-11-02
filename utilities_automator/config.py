"""Read house, tenant and landlord settings from a TOML file."""

from __future__ import annotations

import calendar
import os
import tomllib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

SCRAPED_SOURCES = frozenset({"enbridge", "alectra"})
SOURCES = SCRAPED_SOURCES | {"fixed", "manual"}
MONTHS = tuple(calendar.month_name[1:])


class ConfigError(ValueError):
    """The settings file or .env file is missing something or has a bad value."""


@dataclass(frozen=True)
class Utility:
    """One bill for a house, such as gas, electricity or internet."""

    name: str
    source: str
    amount: Decimal | None = None
    username_env: str | None = None
    password_env: str | None = None

    @property
    def is_scraped(self) -> bool:
        return self.source in SCRAPED_SOURCES

    def credentials(self, environ: Mapping[str, str] | None = None) -> tuple[str, str]:
        """Return (username, password) for this utility's website from the environment."""
        env = os.environ if environ is None else environ
        names = (self.username_env, self.password_env)
        missing = [name for name in names if not env.get(name or "")]
        if missing:
            raise ConfigError(f"{self.name}: set {' and '.join(missing)} in your .env file")
        return env[self.username_env], env[self.password_env]


@dataclass(frozen=True)
class Tenant:
    name: str
    email: str
    rent: Decimal
    share: Decimal


@dataclass(frozen=True)
class House:
    id: str
    name: str
    utilities: tuple[Utility, ...]
    tenants: tuple[Tenant, ...]


@dataclass(frozen=True)
class Landlord:
    name: str
    etransfer_email: str


@dataclass(frozen=True)
class Config:
    landlord: Landlord
    houses: tuple[House, ...]
    workbook: Path
    greetings: Mapping[str, str]

    def house(self, house_id: str) -> House:
        for house in self.houses:
            if house.id == house_id:
                return house
        known = ", ".join(h.id for h in self.houses)
        raise ConfigError(f"No house with id '{house_id}'. Houses in your settings: {known}")


def load_config(path: str | Path) -> Config:
    path = Path(path)
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle, parse_float=Decimal)
    except FileNotFoundError:
        raise ConfigError(
            f"Settings file not found: {path}. "
            f"Copy houses.example.toml to {path.name} and fill it in."
        ) from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from None
    return parse_config(data, base_dir=path.parent)


def parse_config(data: Mapping[str, Any], base_dir: Path = Path(".")) -> Config:
    landlord_table = _table(data, "landlord", "settings file")
    landlord = Landlord(
        name=_text(landlord_table, "name", "[landlord]"),
        etransfer_email=_email(landlord_table, "etransfer_email", "[landlord]"),
    )

    greetings: dict[str, str] = {}
    for month, line in _table(data, "greetings", "settings file", required=False).items():
        key = str(month).strip().capitalize()
        if key not in MONTHS:
            raise ConfigError(f"[greetings]: '{month}' is not a month name")
        greetings[key] = str(line).strip()

    house_tables = data.get("houses") or []
    if not isinstance(house_tables, list) or not house_tables:
        raise ConfigError("Add at least one [[houses]] section to your settings file")
    houses = tuple(_parse_house(table, index) for index, table in enumerate(house_tables, 1))
    _no_duplicates([h.id for h in houses], "house id")
    _no_duplicates([h.name for h in houses], "house name")

    workbook = Path(str(data.get("workbook") or "bills.xlsx"))
    if not workbook.is_absolute():
        workbook = base_dir / workbook

    return Config(landlord=landlord, houses=houses, workbook=workbook, greetings=greetings)


def _parse_house(table: Mapping[str, Any], index: int) -> House:
    if not isinstance(table, Mapping):
        raise ConfigError(f"house #{index} must be a [[houses]] table")
    house_id = str(_require(table, "id", f"house #{index}")).strip()
    where = f"house '{house_id}'"
    name = str(table.get("name") or house_id).strip()

    utility_tables = table.get("utilities") or []
    if not utility_tables:
        raise ConfigError(f"{where}: add at least one [[houses.utilities]] entry")
    utilities = tuple(_parse_utility(u, where) for u in utility_tables)
    _no_duplicates([u.name for u in utilities], f"{where} utility name")

    tenant_tables = table.get("tenants") or []
    if not tenant_tables:
        raise ConfigError(f"{where}: add at least one [[houses.tenants]] entry")
    has_share = [t.get("share") is not None for t in tenant_tables]
    if any(has_share) and not all(has_share):
        raise ConfigError(
            f"{where}: give every tenant a 'share', or leave it out for all of them "
            "to split the bills evenly"
        )
    even_share = None if all(has_share) else Decimal(1) / len(tenant_tables)
    tenants = tuple(_parse_tenant(t, where, even_share) for t in tenant_tables)
    _no_duplicates([t.name for t in tenants], f"{where} tenant name")

    total_share = sum((t.share for t in tenants), Decimal(0))
    if total_share > Decimal("1.0001"):
        raise ConfigError(
            f"{where}: tenant shares add up to {total_share:.0%}, which is more than 100%"
        )

    return House(id=house_id, name=name, utilities=utilities, tenants=tenants)


def _parse_utility(table: Mapping[str, Any], house_where: str) -> Utility:
    name = _text(table, "name", f"{house_where} utility")
    where = f"{house_where} utility '{name}'"
    source = _text(table, "source", where).lower()
    if source not in SOURCES:
        raise ConfigError(f"{where}: source must be one of {', '.join(sorted(SOURCES))}")

    amount = None
    username_env = password_env = None
    if source == "fixed":
        amount = _decimal(_require(table, "amount", where), f"{where} amount")
    elif source in SCRAPED_SOURCES:
        username_env = _text(table, "username_env", where)
        password_env = _text(table, "password_env", where)

    return Utility(
        name=name,
        source=source,
        amount=amount,
        username_env=username_env,
        password_env=password_env,
    )


def _parse_tenant(
    table: Mapping[str, Any], house_where: str, even_share: Decimal | None
) -> Tenant:
    name = _text(table, "name", f"{house_where} tenant")
    where = f"{house_where} tenant '{name}'"
    rent = _decimal(_require(table, "rent", where), f"{where} rent")
    if rent < 0:
        raise ConfigError(f"{where}: rent cannot be negative")
    if even_share is None:
        share = _decimal(table["share"], f"{where} share")
        if not Decimal(0) <= share <= Decimal(1):
            raise ConfigError(f"{where}: share must be between 0 and 1 (0.25 means 25%)")
    else:
        share = even_share
    return Tenant(name=name, email=_email(table, "email", where), rent=rent, share=share)


def _table(data: Mapping[str, Any], key: str, where: str, required: bool = True) -> Mapping:
    value = data.get(key)
    if value is None:
        if required:
            raise ConfigError(f"{where}: missing [{key}] section")
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(f"{where}: [{key}] must be a table")
    return value


def _require(table: Mapping[str, Any], key: str, where: str) -> Any:
    value = table.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ConfigError(f"{where}: missing '{key}'")
    return value


def _text(table: Mapping[str, Any], key: str, where: str) -> str:
    return str(_require(table, key, where)).strip()


def _email(table: Mapping[str, Any], key: str, where: str) -> str:
    value = _text(table, key, where)
    if "@" not in value or value.startswith("@") or value.endswith("@"):
        raise ConfigError(f"{where}: '{value}' does not look like an email address")
    return value


def _decimal(value: Any, where: str) -> Decimal:
    if isinstance(value, bool):
        raise ConfigError(f"{where}: expected a number, got {value}")
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise ConfigError(f"{where}: '{value}' is not a number") from None


def _no_duplicates(values: list[str], what: str) -> None:
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key in seen:
            raise ConfigError(f"Duplicate {what}: '{value}'")
        seen.add(key)
