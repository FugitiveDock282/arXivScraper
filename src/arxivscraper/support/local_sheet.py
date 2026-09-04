## { MODULE

##
## === DEPENDENCIES
##

## stdlib
import datetime
from pathlib import Path
from typing import Any

## third-party
import openpyxl

##
## === LOCAL SPREADSHEET STORE
##

## an .xlsx workbook holds one worksheet per tab; a `LocalSpreadsheet` exposes a
## single worksheet tab as a flat grid of text rows (list of list of str), mirroring
## the grid semantics the sync workflow expects.


def _is_blank(
    cell: Any,
) -> bool:
    """Return whether a raw cell value is blank (empty string or whitespace only)."""
    if cell is None:
        return True
    return isinstance(cell, str) and not cell.strip()


def _cell_to_text(
    cell: Any,
) -> str:
    """Render a raw worksheet cell as the text the user sees.

    Blank cells become `""`; Excel date/datetime values are rendered as
    `YYYY-MM-DD` (times are dropped on midnight-only cells); integral floats are
    rendered without a trailing `.0`. Everything else is stringified as-is.
    """
    if cell is None:
        return ""
    if isinstance(cell, datetime.datetime):
        if cell.hour == 0 and cell.minute == 0 and cell.second == 0:
            return cell.date().isoformat()
        return cell.isoformat(sep=" ")
    if isinstance(cell, datetime.date):
        return cell.isoformat()
    if isinstance(cell, float) and cell.is_integer():
        return str(int(cell))
    return str(cell)


class LocalSpreadsheet:
    """A single worksheet (tab) inside a local `.xlsx` workbook.

    Parameters
    ---
    - `file_path`:
        Path to the `.xlsx` workbook on disk; created on first write if missing.
    - `sheet_name`:
        Name of the worksheet tab to read from / write to; created on first write
        if it does not exist.
    """

    def __init__(
        self,
        file_path: Path,
        sheet_name: str = "Papers",
    ) -> None:
        self.file_path = file_path
        self.sheet_name = sheet_name

    def read_all_rows(
        self,
    ) -> list[list[str]]:
        """Return every row in the worksheet as lists of strings.

        Returns an empty list when the file does not exist, the worksheet is
        missing, or the worksheet holds no data rows.

        Only cells that actually hold a value count towards the returned grid's
        extent; cells that are merely styled but empty (formatting applied to an
        empty area) do not widen or lengthen the grid. Rows are returned padded
        to the grid's column width, and trailing fully-blank rows are trimmed so
        an empty sheet reads back as no rows.
        """
        if not self.file_path.is_file():
            return []
        workbook = openpyxl.load_workbook(
            self.file_path,
            data_only=False,
        )
        if self.sheet_name not in workbook.sheetnames:
            return []
        worksheet = workbook[self.sheet_name]
        last_content_row = 0
        last_content_column = 0
        for cell in worksheet._cells.values():
            if _is_blank(cell.value):
                continue
            if cell.row is not None:
                last_content_row = max(last_content_row, cell.row)
            if cell.column is not None:
                last_content_column = max(last_content_column, cell.column)
        if last_content_row == 0:
            return []
        rows = [
            [_cell_to_text(cell) for cell in row]
            for row in worksheet.iter_rows(
                max_row=last_content_row,
                max_col=last_content_column,
                values_only=True,
            )
        ]
        while rows and not any(rows[-1]):
            rows.pop()
        return rows

    def write_all_rows(
        self,
        rows: list[list[Any]],
    ) -> None:
        """Overwrite the worksheet's content with `rows`, keeping cell formatting.

        Values are written in place: cells that already exist keep their style
        (bold headers, fills, column widths, etc. survive a rewrite). Any content
        that previously existed but falls outside the new grid is cleared, but
        the formatting of those cells is left untouched.

        Creates the workbook (and any missing parent directories) and the
        worksheet tab when they do not already exist. Existing worksheets that
        are not the configured one are left untouched.
        """
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        creating_file = not self.file_path.is_file()
        workbook = openpyxl.Workbook() if creating_file else openpyxl.load_workbook(
            self.file_path,
        )
        worksheet = None
        if creating_file:
            worksheet = workbook.active
            assert worksheet is not None
            worksheet.title = self.sheet_name
        elif self.sheet_name in workbook.sheetnames:
            worksheet = workbook[self.sheet_name]
        else:
            worksheet = workbook.create_sheet(title=self.sheet_name)
        old_content: list[tuple[int, int]] = [
            (cell.row, cell.column)
            for cell in worksheet._cells.values()
            if (cell.row is not None and cell.column is not None and not _is_blank(cell.value))
        ]
        new_height = len(rows)
        new_width = max((len(row) for row in rows), default=0)
        for row_index, row in enumerate(rows, start=1):
            for column_index, value in enumerate(row, start=1):
                _set_cell_value(
                    worksheet,
                    row=row_index,
                    column=column_index,
                    value=value,
                )
        for row_index, column_index in old_content:
            if row_index > new_height or column_index > new_width:
                _set_cell_value(
                    worksheet,
                    row=row_index,
                    column=column_index,
                    value=None,
                )
        workbook.save(self.file_path)


def _set_cell_value(
    worksheet: Any,
    *,
    row: int,
    column: int,
    value: str | None,
) -> None:
    """Write `value` into a worksheet cell without disturbing its existing style.

    Blank values (`None` or whitespace-only) clear any existing content instead
    of creating a new cell, so an empty area never grows the sheet's extent.
    """
    coordinate = (row, column)
    existing = worksheet._cells.get(coordinate)
    if value is None or _is_blank(value):
        if existing is not None:
            existing.value = None
        return
    if existing is None:
        worksheet.cell(row=row, column=column, value=value)
    else:
        existing.value = value


## } MODULE
