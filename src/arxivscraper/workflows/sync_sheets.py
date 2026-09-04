## { SCRIPT

##
## === DEPENDENCIES
##
## stdlib
import sys
import tomllib
from pathlib import Path
from typing import Any

## third-party
import gspread
from google.auth import credentials as google_credentials
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as OAuth2Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

## local
from arxivscraper.config_paths import directories, files as config_files
from arxivscraper.support import articles, file_io, sheet_mapping

##
## === SHEETS CONFIG
##


def load_sheets_config(
) -> dict[str, Any]:
    """Load and validate `configs/sheets/sheets_config.toml`."""
    config_path = directories.sheets_configs_dir / config_files.sheets_config
    if not config_path.is_file():
        raise FileNotFoundError(
            f"no sheets config found; create `{config_path.name}` "
            f"(see `{config_files.sheets_config_example}`).",
        )
    try:
        with config_path.open("rb") as file_pointer:
            config = tomllib.load(file_pointer)
    except Exception as error:
        raise ValueError(f"error reading `{config_path.name}`.") from error
    has_service_account = bool(config.get("service_account_json"))
    has_oauth = bool(config.get("oauth_client_json"))
    if has_service_account == has_oauth:
        raise ValueError(
            "provide exactly one of `service_account_json` (service account) "
            "or `oauth_client_json` (user OAuth) in sheets config.",
        )
    if has_oauth and not config.get("token_json"):
        raise ValueError("provide `token_json` when authenticating with user OAuth.")
    if not (config.get("spreadsheet_id") or config.get("spreadsheet_url")):
        raise ValueError("provide either `spreadsheet_id` or `spreadsheet_url` in sheets config.")
    sync_mode = config.get("sync_mode", "bidirectional")
    if sync_mode not in ("push", "pull", "bidirectional"):
        raise ValueError(f"`sync_mode` must be `push`, `pull`, or `bidirectional`; got `{sync_mode}`.")
    config["sync_mode"] = sync_mode
    return config


##
## === SHEETS CLIENT
##

_SHEET_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _get_user_credentials(
    config: dict[str, Any],
) -> google_credentials.Credentials:
    """Load a previously-saved user token or run the OAuth consent flow to create one."""
    token_path = Path(config["token_json"])
    if token_path.is_file():
        return OAuth2Credentials.from_authorized_user_file(
            str(token_path),
            scopes=_SHEET_SCOPES,
        )
    flow = InstalledAppFlow.from_client_secrets_file(
        config["oauth_client_json"],
        scopes=_SHEET_SCOPES,
    )
    credentials = flow.run_local_server(port=0)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    with open(token_path, "w") as file_pointer:
        file_pointer.write(credentials.to_json())
    return credentials


def create_sheets_client(
    config: dict[str, Any],
) -> gspread.Client:
    """Create a `gspread` client using either a service account or user OAuth credentials."""
    if config.get("service_account_json"):
        credentials = service_account.Credentials.from_service_account_file(
            config["service_account_json"],
            scopes=_SHEET_SCOPES,
        )
    else:
        credentials = _get_user_credentials(config)
    return gspread.authorize(credentials)


def open_worksheet(
    config: dict[str, Any],
) -> gspread.Worksheet:
    """Open the configured worksheet (tab), creating it if it does not exist."""
    client = create_sheets_client(config)
    if config.get("spreadsheet_id"):
        spreadsheet = client.open_by_key(config["spreadsheet_id"])
    else:
        spreadsheet = client.open_by_url(config["spreadsheet_url"])
    sheet_name = config.get("sheet_name", "Papers")
    try:
        return spreadsheet.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=sheet_name,
            rows=100,
            cols=len(sheet_mapping.SHEET_HEADER),
        )
        worksheet.update(
            [sheet_mapping.header_row()],
            value_input_option=gspread.utils.ValueInputOption.raw,
        )
        print(f"Created worksheet `{sheet_name}` in the spreadsheet.")
        return worksheet


##
## === PUSH (MD -> SHEET)
##


def push_to_sheets(
    *,
    config: dict[str, Any],
) -> None:
    """Write all mdfiles as rows into the sheet, overwriting the data area."""
    worksheet = open_worksheet(config)
    articles_list = articles.read_all_markdown_files()
    rows = [sheet_mapping.header_row()] + [
        sheet_mapping.article_to_row(article) for article in articles_list
    ]
    worksheet.clear()
    worksheet.update(
        rows,
        value_input_option=gspread.utils.ValueInputOption.raw,
    )
    print(f"Pushed {len(articles_list)} article(s) to `{config.get('sheet_name', 'Papers')}`.")


##
## === PULL (SHEET -> MD)
##


def pull_from_sheets(
    *,
    config: dict[str, Any],
) -> None:
    """Write every sheet row back to its mdfile, retaining md-only state from existing files.

    The sheet is the editing surface, so non-empty sheet values win; empty sheet cells
    never clobber populated mdfile fields, and `config_reasons` are retained from the
    existing mdfile (see `sheet_mapping.merge_pull_article`). mdfiles with no matching
    sheet row are left untouched.
    """
    worksheet = open_worksheet(config)
    sheet_rows = worksheet.get_all_values()
    if not sheet_rows:
        print("Sheet is empty; nothing to pull.")
        return
    header = sheet_rows[0]
    if header != sheet_mapping.header_row():
        raise ValueError(f"unexpected sheet header; got `{header}`.")
    file_io.create_directory(directories.md_files_dir)
    num_updated = 0
    num_failed = 0
    for row_index, raw_row in enumerate(sheet_rows[1:], start=2):
        if not any(raw_row):
            continue
        try:
            incoming = sheet_mapping.row_to_article(raw_row)
        except ValueError as error:
            print(f"Skipping sheet row {row_index}: {error}.")
            num_failed += 1
            continue
        md_path = directories.md_files_dir / f"{incoming.arxiv_id}.md"
        existing = articles.read_markdown_file(md_path) if md_path.exists() else None
        incoming = sheet_mapping.merge_pull_article(incoming, existing)
        with open(md_path, "w") as file_pointer:
            articles.write_article_to_file(file_pointer, article=incoming)
        num_updated += 1
    print(f"Pulled {num_updated} article(s) from `{config.get('sheet_name', 'Papers')}`.")
    if num_failed:
        print(f"Skipped {num_failed} malformed row(s).")


##
## === PROGRAM MAIN
##


def main() -> None:
    config = load_sheets_config()
    sync_mode = config["sync_mode"]
    if sync_mode in ("pull", "bidirectional"):
        pull_from_sheets(config=config)
    if sync_mode in ("push", "bidirectional"):
        push_to_sheets(config=config)


##
## === ENTRY POINT
##

if __name__ == "__main__":
    main()
    sys.exit(0)

## } SCRIPT
