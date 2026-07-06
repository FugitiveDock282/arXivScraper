## { SCRIPT

##
## === DEPENDENCIES
##

## stdlib
import subprocess
import sys
import webbrowser
from typing import ClassVar

## third-party
from rich.markup import escape as rich_escape
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.widgets import DataTable, Footer, Header, Input, Static

## local
from arxivscraper.config_paths import directories
from arxivscraper.support import articles, dates, file_io
from arxivscraper.support.articles import TaskStatus
from arxivscraper.workflows import download_pdfs

##
## === CONSTANTS
##

_FILTER_CYCLE: list[TaskStatus | None] = [
    None,
    TaskStatus.PENDING,
    TaskStatus.QUEUED,
    TaskStatus.READ,
    TaskStatus.DOWNLOAD,
    TaskStatus.NA,
    TaskStatus.DELETE,
]


def _format_score(
    ai_rating: float | None,
) -> str:
    return "-" if ai_rating is None else f"{ai_rating:g}"


class SearchInput(Input):
    """Search box that can hand focus back to the results table."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding(
            key="up",
            action="focus_table",
            description="table",
        ),
        Binding(
            key="down",
            action="focus_table",
            description="table",
        ),
        Binding(
            key="escape",
            action="focus_table",
            description="table",
        ),
    ]

    def action_focus_table(
        self,
    ) -> None:
        self.app.action_focus_table()


class BrowseApp(App[None]):
    """TUI browser for reviewing and triaging saved arXiv articles."""

    CSS = """
    DataTable {
        height: 3fr;
    }
    #search {
        margin: 0 0 1 0;
    }
    #abstract {
        height: 2fr;
        border: solid $accent;
        padding: 1 2;
        overflow-y: auto;
    }
    """

    TITLE = "arXiv Browser"

    BINDINGS: ClassVar[list[BindingType]] = [
        *(
            Binding(
                key=status.key,
                action=f"set_status('{status.value}')",
                description=status.description,
            ) for status in TaskStatus
        ),
        Binding(
            key="D",
            action="apply_downloads",
            description="apply download",
        ),
        Binding(
            key="X",
            action="apply_deletions",
            description="apply delete",
        ),
        Binding(
            key="o",
            action="open_pdf",
            description="open PDF",
        ),
        Binding(
            key="e",
            action="open_md",
            description="edit MD",
        ),
        Binding(
            key="f",
            action="cycle_filter",
            description="filter",
        ),
        Binding(
            key="s",
            action="toggle_search",
            description="search",
        ),
        Binding(
            key="S",
            action="toggle_sort",
            description="sort",
        ),
        Binding(
            key="escape",
            action="escape",
            description="quit",
        ),
    ]

    def __init__(
        self,
        articles_list: list[articles.Article],
    ) -> None:
        super().__init__()
        self.all_articles = articles_list
        self.filter_status: TaskStatus | None = None
        self.search_query = ""
        self.sort_by_score = False

    def compose(
        self,
    ) -> ComposeResult:
        yield Header()
        yield SearchInput(
            placeholder="search title, abstract, authors, tags, id, category",
            id="search",
        )
        yield DataTable()
        yield Static(id="abstract")
        yield Footer()

    def on_mount(
        self,
    ) -> None:
        table = self.query_one(DataTable)
        search_input = self.query_one(Input)
        search_input.display = False
        table.cursor_type = "row"
        table.add_columns("Status", "Score", "Tags", "Category", "Date", "ID", "Title")
        table.focus()
        self._refresh_table()

    def _get_visible_articles(
        self,
    ) -> list[articles.Article]:
        visible_articles = self.all_articles
        if self.filter_status is not None:
            visible_articles = [
                article for article in visible_articles
                if article.task_status == self.filter_status
            ]
        if self.search_query:
            visible_articles = [
                article for article in visible_articles
                if self._article_matches_query(
                    article=article,
                    query=self.search_query,
                )
            ]
        if self.sort_by_score:
            visible_articles = sorted(
                visible_articles,
                key=lambda article: (
                    article.ai_rating if article.ai_rating is not None else -1
                ),
                reverse=True,
            )
        return visible_articles

    def _article_matches_query(
        self,
        *,
        article: articles.Article,
        query: str,
    ) -> bool:
        haystack = " ".join(
            [
                article.title,
                article.abstract,
                " ".join(article.authors),
                " ".join(article.config_tags),
                article.arxiv_id,
                article.category_primary,
                " ".join(article.category_others),
            ],
        ).lower()
        return query.lower() in haystack

    def _refresh_table(
        self,
        *,
        keep_row: int = 0,
    ) -> None:
        table = self.query_one(DataTable)
        table.clear()
        visible_articles = self._get_visible_articles()
        for article in visible_articles:
            table.add_row(
                article.task_status.value,
                _format_score(article.ai_rating),
                " ".join(article.config_tags),
                article.category_primary,
                str(article.date_updated),
                article.arxiv_id,
                article.title,
            )
        if visible_articles:
            row = min(keep_row, len(visible_articles) - 1)
            table.move_cursor(
                row=row,
                scroll=True,
            )
            self._update_abstract(row_index=row)
        else:
            self.query_one("#abstract", Static).update("[dim]No papers match this filter.[/dim]")
        self._update_subtitle()

    def _update_abstract(
        self,
        *,
        row_index: int,
    ) -> None:
        visible_articles = self._get_visible_articles()
        if not visible_articles:
            return
        article = visible_articles[row_index]
        categories = ", ".join([article.category_primary, *article.category_others])
        tags = ", ".join(article.config_tags) or "-"
        if article.ai_rating is None:
            score_block = "[bold]score:[/bold] [dim]not yet scored.[/dim]"
        else:
            score_block = (
                f"[bold]score:[/bold] {_format_score(article.ai_rating)}\n"
                f"[bold]reason:[/bold] {rich_escape(article.ai_reason or '')}"
            )
        self.query_one("#abstract", Static).update(
            f"[bold]title:[/bold] {rich_escape(article.title)}\n"
            f"[bold]authors:[/bold] {rich_escape(', '.join(article.authors))}\n"
            f"[bold]published:[/bold] {dates.as_date_string(article.date_published)}"
            f"   [bold]updated:[/bold] {dates.as_date_string(article.date_updated)}\n"
            f"[bold]categories:[/bold] {rich_escape(categories)}\n"
            f"[bold]tags:[/bold] {rich_escape(tags)}\n\n"
            f"[bold]abstract:[/bold] {rich_escape(article.abstract)}\n\n"
            f"{score_block}",
        )

    def _update_subtitle(
        self,
    ) -> None:
        visible_articles = self._get_visible_articles()
        filter_label = "all" if self.filter_status is None else self.filter_status.value
        search_label = self.search_query if self.search_query else "off"
        sort_label = "score" if self.sort_by_score else "date"
        self.sub_title = (
            f"filter: {filter_label}  "
            f"search: {search_label}  "
            f"sort: {sort_label}  "
            f"({len(visible_articles)} papers)"
        )

    def on_input_changed(
        self,
        event: Input.Changed,
    ) -> None:
        if event.input.id != "search":
            return
        self.search_query = event.value.strip()
        self._refresh_table()

    def on_data_table_row_highlighted(
        self,
        event: DataTable.RowHighlighted,
    ) -> None:
        self._update_abstract(row_index=event.cursor_row)

    def _get_current_article(
        self,
    ) -> articles.Article | None:
        table = self.query_one(DataTable)
        visible_articles = self._get_visible_articles()
        if not visible_articles:
            return None
        return visible_articles[table.cursor_row]

    def action_set_status(
        self,
        status: str,
    ) -> None:
        table = self.query_one(DataTable)
        current_row = table.cursor_row
        article = self._get_current_article()
        if article is None:
            return
        article.task_status = TaskStatus(status)
        file_path = directories.md_files_dir / f"{article.arxiv_id}.md"
        with open(file_path, "w") as file_pointer:
            articles.write_article_to_file(file_pointer, article=article)
        self._refresh_table(keep_row=current_row)

    def action_open_pdf(
        self,
    ) -> None:
        article = self._get_current_article()
        if article is None:
            return
        webbrowser.open(article.url_pdf)

    def action_open_md(
        self,
    ) -> None:
        article = self._get_current_article()
        if article is None:
            return
        file_path = directories.md_files_dir / f"{article.arxiv_id}.md"
        subprocess.Popen(["open", str(file_path)])

    def action_apply_downloads(
        self,
    ) -> None:
        file_io.create_directory(directories.pdfs_dir)
        download_pdfs.download_pdfs(self.all_articles)
        self._refresh_table()

    def action_apply_deletions(
        self,
    ) -> None:
        to_delete = [article for article in self.all_articles if article.task_status == TaskStatus.DELETE]
        for article in to_delete:
            (directories.md_files_dir / f"{article.arxiv_id}.md").unlink(missing_ok=True)
            self.all_articles.remove(article)
        self._refresh_table()

    def action_cycle_filter(
        self,
    ) -> None:
        current_index = _FILTER_CYCLE.index(self.filter_status)
        self.filter_status = _FILTER_CYCLE[(current_index + 1) % len(_FILTER_CYCLE)]
        self._refresh_table()

    def action_toggle_sort(
        self,
    ) -> None:
        self.sort_by_score = not self.sort_by_score
        self._refresh_table()

    def action_toggle_search(
        self,
    ) -> None:
        search_input = self.query_one(SearchInput)
        search_input.display = not search_input.display
        if search_input.display:
            self.call_after_refresh(search_input.focus)
            return
        self.search_query = ""
        search_input.value = ""
        self.query_one(DataTable).focus()
        self._refresh_table()

    def action_focus_table(
        self,
    ) -> None:
        self.query_one(DataTable).focus()

    def action_escape(
        self,
    ) -> None:
        search_input = self.query_one(SearchInput)
        if search_input.has_focus:
            self.action_focus_table()
            return
        self.exit()


##
## === PROGRAM MAIN
##


def main() -> None:
    articles_list = articles.read_all_markdown_files()
    articles_list = sorted(
        articles_list,
        key=lambda article: article.date_updated,
        reverse=True,
    )
    BrowseApp(articles_list).run()


##
## === ENTRY POINT
##

if __name__ == "__main__":
    main()
    sys.exit(0)

## } SCRIPT
