"""Keep a running log of each house's bills in an Excel workbook."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from .billing import HouseBill

MONEY_FORMAT = '"$"#,##0.00'
MONTH_FORMAT = "mmm yyyy"
DATE_FORMAT = "yyyy-mm-dd"
_BAD_SHEET_CHARS = set("[]:*?/\\")


def sheet_title(name: str) -> str:
    """Excel sheet names are at most 31 characters and cannot use []:*?/\\."""
    cleaned = "".join("-" if ch in _BAD_SHEET_CHARS else ch for ch in name).strip()
    return cleaned[:31] or "House"


def bill_row(bill: HouseBill, recorded_on: date) -> dict[str, object]:
    row: dict[str, object] = {"Month": bill.month, "Recorded on": recorded_on}
    row.update(bill.utility_amounts)
    row["Utilities total"] = bill.utilities_total
    row["Not charged to tenants"] = bill.not_charged
    for tenant_bill in bill.tenant_bills:
        name = tenant_bill.tenant.name
        row[f"{name} utilities"] = tenant_bill.utilities_total
        row[f"{name} total due"] = tenant_bill.total_due
    return row


def record_bills(path: Path, bills: Iterable[HouseBill], recorded_on: date | None = None) -> None:
    """Add one row per house to that house's sheet.

    Running again for the same month replaces that month's row, so a re-run
    never creates duplicates. New tenants or utilities get new columns.
    """
    path = Path(path)
    if path.exists():
        workbook = load_workbook(path)
    else:
        workbook = Workbook()
        workbook.remove(workbook.active)

    recorded_on = recorded_on or date.today()
    for bill in bills:
        title = sheet_title(bill.house.name)
        sheet = workbook[title] if title in workbook.sheetnames else workbook.create_sheet(title)
        _write_row(sheet, bill_row(bill, recorded_on))

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        workbook.save(path)
    except PermissionError:
        raise PermissionError(f"Could not save {path}. Close it in Excel and run again.") from None


def _write_row(sheet: Worksheet, row: dict[str, object]) -> None:
    headers = [cell.value for cell in sheet[1]]
    while headers and headers[-1] is None:
        headers.pop()
    for key in row:
        if key not in headers:
            headers.append(key)
            cell = sheet.cell(row=1, column=len(headers), value=key)
            cell.font = Font(bold=True)
            sheet.column_dimensions[get_column_letter(len(headers))].width = max(12, len(key) + 2)
    sheet.freeze_panes = "A2"

    month_column = headers.index("Month") + 1
    target = _find_month_row(sheet, month_column, row["Month"]) or sheet.max_row + 1

    for column, key in enumerate(headers, 1):
        value = row.get(key)
        cell = sheet.cell(row=target, column=column, value=value)
        if isinstance(value, Decimal):
            cell.number_format = MONEY_FORMAT
        elif isinstance(value, date):
            cell.number_format = MONTH_FORMAT if key == "Month" else DATE_FORMAT


def _find_month_row(sheet: Worksheet, column: int, month: object) -> int | None:
    for row_number in range(2, sheet.max_row + 1):
        value = sheet.cell(row=row_number, column=column).value
        if isinstance(value, datetime):
            value = value.date()
        if value == month:
            return row_number
    return None
