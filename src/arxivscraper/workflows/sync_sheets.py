## { SCRIPT

##
## === DEPENDENCIES
##
## stdlib
import sys
import tomllib
from pathlib import Path
from typing import Any

## local
from arxivscraper.config_paths import directories, files as config_files
from arxivscraper.support import articles, file_io, local_sheet, sheet_mapping

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
    spreadsheet_path_value = config.get("spreadsheet_path")
    if not spreadsheet_path_value:
        raise ValueError("provide `spreadsheet_path` in sheets config.")
    spreadsheet_path = Path(spreadsheet_path_value).expanduser()
    if not spreadsheet_path.is_absolute():
        spreadsheet_path = (config_path.parent / spreadsheet_path).resolve()
    if spreadsheet_path.suffix.lower() != ".xlsx":
        raise ValueError(
            f"`spreadsheet_path` must point to a `.xlsx` file; got `{spreadsheet_path}`.",
        )
    sheet_name = config.get("sheet_name", "Papers")
    if not sheet_name:
        raise ValueError("`sheet_name` must be a non-empty string in sheets config.")
    sync_mode = config.get("sync_mode", "bidirectional")
    if sync_mode not in ("push", "pull", "bidirectional"):
        raise ValueError(f"`sync_mode` must be `push`, `pull`, or `bidirectional`; got `{sync_mode}`.")
    return {
        "spreadsheet_path": spreadsheet_path,
        "sheet_name": sheet_name,
        "sync_mode": sync_mode,
    }


##
## === PUSH (MD -> SHEET)
##


def push_to_sheets(
    *,
    config: dict[str, Any],
) -> None:
    """Write all mdfiles as rows into the local spreadsheet, overwriting the data area.

    Abstracts with AI evidence are written as rich text so the flagged quotes show
    up green (positive) or red (negative); plain-text abstracts are written as-is.
    """
    spreadsheet = local_sheet.LocalSpreadsheet(
        file_path=config["spreadsheet_path"],
        sheet_name=config["sheet_name"],
    )
    articles_list = articles.read_all_markdown_files()
    abstract_column = sheet_mapping.SHEET_HEADER.index("abstract")
    rows: list[list[Any]] = [sheet_mapping.header_row()]
    for article in articles_list:
        row: list[Any] = sheet_mapping.article_to_row(article)
        row[abstract_column] = local_sheet.render_abstract_cell(
            abstract=article.abstract,
            highlights=[
                (quote.quote, quote.effect)
                for quote in article.ai_evidence
            ],
        )
        rows.append(row)
    spreadsheet.write_all_rows(rows)
    print(
        f"Pushed {len(articles_list)} article(s) to "
        f"`{config['sheet_name']}` in `{config['spreadsheet_path']}`.",
    )


##
## === PULL (SHEET -> MD)
##


def pull_from_sheets(
    *,
    config: dict[str, Any],
) -> None:
    """Write every sheet row back to its mdfile, retaining md-only state from existing files.

    The spreadsheet is the editing surface, so non-empty sheet values win; empty
    sheet cells never clobber populated mdfile fields, and `config_reasons` are
    retained from the existing mdfile (see `sheet_mapping.merge_pull_article`).
    mdfiles with no matching sheet row are left untouched.
    """
    spreadsheet = local_sheet.LocalSpreadsheet(
        file_path=config["spreadsheet_path"],
        sheet_name=config["sheet_name"],
    )
    sheet_rows = spreadsheet.read_all_rows()
    if not sheet_rows:
        print(
            f"Spreadsheet `{config['spreadsheet_path']}` is empty or missing; nothing to pull.",
        )
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
    print(
        f"Pulled {num_updated} article(s) from "
        f"`{config['sheet_name']}` in `{config['spreadsheet_path']}`.",
    )
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
