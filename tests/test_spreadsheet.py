from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

from openpyxl import load_workbook

from utilities_automator.billing import calculate_house_bill
from utilities_automator.config import Tenant
from utilities_automator.spreadsheet import MONEY_FORMAT, record_bills, sheet_title


def amounts(gas):
    return {"Gas": Decimal(gas), "Electricity": Decimal("18.18"), "Internet": Decimal(45)}


def rows(path, sheet):
    ws = load_workbook(path)[sheet]
    return [list(r) for r in ws.iter_rows(values_only=True)]


def test_writes_one_sheet_per_house_with_headers(tmp_path, house):
    other = replace(house, id="23", name="23 House")
    path = tmp_path / "bills.xlsx"
    month = date(2026, 11, 1)

    record_bills(
        path,
        [calculate_house_bill(house, amounts("107.50"), month), calculate_house_bill(other, amounts(50), month)],
        recorded_on=date(2026, 11, 2),
    )

    workbook = load_workbook(path)
    assert workbook.sheetnames == ["58 House", "23 House"]
    header, row = rows(path, "58 House")
    assert header == [
        "Month", "Recorded on", "Gas", "Electricity", "Internet", "Utilities total",
        "Not charged to tenants", "Upstairs A utilities", "Upstairs A total due",
        "Master utilities", "Master total due",
    ]
    assert row[0] == datetime(2026, 11, 1)
    assert row[2:6] == [107.5, 18.18, 45, 170.68]
    assert row[8] == 1337.55
    assert workbook["58 House"]["C2"].number_format == MONEY_FORMAT


def test_rerunning_a_month_replaces_its_row(tmp_path, house):
    path = tmp_path / "bills.xlsx"
    record_bills(path, [calculate_house_bill(house, amounts(100), date(2026, 10, 1))])
    record_bills(path, [calculate_house_bill(house, amounts(100), date(2026, 11, 1))])
    record_bills(path, [calculate_house_bill(house, amounts(200), date(2026, 11, 1))])

    data = rows(path, "58 House")
    assert len(data) == 3
    assert [r[2] for r in data[1:]] == [100, 200]


def test_new_tenant_gets_new_columns(tmp_path, house):
    path = tmp_path / "bills.xlsx"
    record_bills(path, [calculate_house_bill(house, amounts(100), date(2026, 10, 1))])
    newcomer = Tenant(name="Basement", email="b@example.com", rent=Decimal(900), share=Decimal("0.1"))
    bigger = replace(house, tenants=house.tenants + (newcomer,))
    record_bills(path, [calculate_house_bill(bigger, amounts(100), date(2026, 11, 1))])

    header, october, november = rows(path, "58 House")
    assert header[-2:] == ["Basement utilities", "Basement total due"]
    assert october[-1] is None
    assert november[-1] == 916.32  # 900 rent + 10% of 163.18 in bills


def test_sheet_title_is_excel_safe():
    assert sheet_title("58/60 Main St: [rear]") == "58-60 Main St- -rear-"
    assert len(sheet_title("x" * 50)) == 31
