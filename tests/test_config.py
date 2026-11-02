import copy
import tomllib
from decimal import Decimal
from pathlib import Path

import pytest

from utilities_automator.config import ConfigError, load_config, parse_config

from .conftest import SETTINGS

EXAMPLE = Path(__file__).resolve().parent.parent / "houses.example.toml"


def base():
    return copy.deepcopy(tomllib.loads(SETTINGS, parse_float=Decimal))


def test_example_settings_file_is_valid():
    config = load_config(EXAMPLE)
    assert [h.id for h in config.houses] == ["58", "23"]
    assert config.workbook == EXAMPLE.parent / "bills.xlsx"


def test_loads_houses_tenants_and_greetings(settings_file):
    config = load_config(settings_file)
    house = config.house("58")
    assert [u.name for u in house.utilities] == ["Gas", "Internet"]
    assert house.utilities[0].is_scraped
    assert house.utilities[1].amount == Decimal("45.00")
    assert house.tenants[0].share == Decimal("0.22")
    assert config.greetings == {"November": "Happy November!"}
    assert config.workbook == settings_file.parent / "bills.xlsx"


def test_tenants_without_share_split_evenly():
    data = base()
    data["houses"][1]["tenants"].append({"name": "Downstairs B", "email": "b@example.com", "rent": 1300})
    house = parse_config(data).house("23")
    assert [t.share for t in house.tenants] == [Decimal("0.5"), Decimal("0.5")]


def test_unknown_house_lists_known_ids(settings_file):
    with pytest.raises(ConfigError, match="Houses in your settings: 58, 23"):
        load_config(settings_file).house("99")


def test_missing_file_explains_how_to_start(tmp_path):
    with pytest.raises(ConfigError, match="Copy houses.example.toml"):
        load_config(tmp_path / "houses.toml")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["houses"][0]["tenants"][0].pop("share"), "give every tenant a 'share'"),
        (lambda d: d["houses"][0]["tenants"][0].update(share=Decimal("0.9")), "more than 100%"),
        (lambda d: d["houses"][0]["tenants"][0].update(share=Decimal("22")), "between 0 and 1"),
        (lambda d: d["houses"][1].update(id="58"), "Duplicate house id"),
        (lambda d: d["houses"][0]["utilities"][1].pop("amount"), "missing 'amount'"),
        (lambda d: d["houses"][0]["utilities"][0].pop("password_env"), "missing 'password_env'"),
        (lambda d: d["houses"][0]["utilities"][0].update(source="hydro"), "source must be one of"),
        (lambda d: d["houses"][0]["tenants"][1].update(name="upstairs a"), "Duplicate house '58' tenant"),
        (lambda d: d["houses"][0]["tenants"][1].update(email="nope"), "does not look like an email"),
        (lambda d: d["greetings"].update(Smarch="hi"), "not a month name"),
        (lambda d: d.pop("landlord"), r"missing \[landlord\]"),
        (lambda d: d.update(houses=[]), "at least one"),
    ],
)
def test_bad_settings_give_clear_errors(change, message):
    data = base()
    change(data)
    with pytest.raises(ConfigError, match=message):
        parse_config(data)


def test_credentials_name_the_missing_env_vars(settings_file):
    gas = load_config(settings_file).house("58").utilities[0]
    with pytest.raises(ConfigError, match="set H58_GAS_USER and H58_GAS_PASS"):
        gas.credentials({})
    assert gas.credentials({"H58_GAS_USER": "u", "H58_GAS_PASS": "p"}) == ("u", "p")
