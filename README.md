# Utilities Automator

Each month this tool:

1. Logs in to Enbridge Gas and Alectra Utilities for **each house** and reads the latest bill.
2. Splits every bill between that house's tenants using each tenant's share.
3. Saves the bills and what each tenant owes to `bills.xlsx` (one sheet per house).
4. Emails each tenant their rent plus their utilities breakdown, after you say yes.

If a utility website changes and the login fails, the tool asks you to type the amount instead, so a run never gets stuck.

## Setup

You need Python 3.11 or newer and Google Chrome. Selenium downloads the matching Chrome driver by itself, so there is no `chromedriver.exe` to manage.

```bash
python -m venv .venv
```

Activate it (`.venv\Scripts\activate` on Windows, `source .venv/bin/activate` on Mac or Linux), then:

```bash
pip install -r requirements.txt
```

Then create your two private files from the examples:

```bash
cp houses.example.toml houses.toml
cp .env.example .env
```

- **`houses.toml`**: houses, utilities, tenants, rent and shares. Read the comments in the file.
- **`.env`**: passwords only. For Gmail, create an [app password](https://myaccount.google.com/apppasswords) (2-Step Verification must be on) and use that, not your normal password.

Both files and `bills.xlsx` are in `.gitignore` so tenant details and passwords never get committed. Keep this repository **private** anyway.

## Monthly run

Check everything first without saving or sending:

```bash
python -m utilities_automator --dry-run
```

Then do the real run. It saves to the spreadsheet and asks before each email:

```bash
python -m utilities_automator
```

Useful options:

| Option | What it does |
| --- | --- |
| `--house 58` | Only run one house. Repeat it for more than one. |
| `--month 2026-12` | Bill a different rent month. Default is this month. |
| `--manual` | Type in every amount instead of logging in to the websites. |
| `--no-email` | Save to the spreadsheet but send nothing. |
| `--yes` | Send all emails without asking each time. |
| `--show-browser` | Watch Chrome log in. Handy when a scraper breaks. |

Running the same month again **replaces** that month's row in the spreadsheet, so you never get duplicates. Close `bills.xlsx` in Excel before a run or it cannot be saved.

## How the split works

- Each tenant has a `share`, such as `0.22` for 22%. They pay that part of **every** bill, rounded to the cent.
- Shares can add up to less than 100%. The rest shows as "Not charged to tenants", which is your part.
- Leave out `share` for every tenant in a house to split its bills evenly.
- Each line in the email is rounded first and the total is the sum of those lines, so the email always adds up.

Example with a 22% share and $1,300 rent:

```
Gas: $23.65 (of $107.50)
Electricity: $4.00 (of $18.18)
Internet: $9.90 (of $45.00)
Utilities total: $37.55

Rent: $1,300.00
Total due: $1,337.55
```

## Adding a utility or a house

- **Fixed bill** (internet, water flat rate): add a `[[houses.utilities]]` entry with `source = "fixed"` and an `amount`.
- **Bill you type in each month**: use `source = "manual"`.
- **New house**: copy a whole `[[houses]]` block, give it a new `id` and `name`, and add its logins to `.env`.
- **New tenant**: add a `[[houses.tenants]]` entry. The spreadsheet adds new columns for them automatically.

## When a scraper breaks

Utility websites change. When one does:

1. The run tells you what failed and saves a screenshot in `debug/`. Then it asks you for the amount so you can finish the month.
2. Run `python -m utilities_automator --house 58 --show-browser --dry-run` to watch what happens.
3. Update the URL or element IDs in `utilities_automator/scrapers.py` (`fetch_enbridge` or `fetch_alectra`).

## Development

```bash
pip install -r requirements-dev.txt
```

```bash
python -m pytest
```

| File | Job |
| --- | --- |
| `utilities_automator/config.py` | Reads and checks `houses.toml` |
| `utilities_automator/scrapers.py` | Logs in to Enbridge and Alectra |
| `utilities_automator/billing.py` | Splits bills between tenants |
| `utilities_automator/spreadsheet.py` | Writes `bills.xlsx` |
| `utilities_automator/emailer.py` | Writes and sends the emails |
| `utilities_automator/cli.py` | Runs the monthly steps in order |
