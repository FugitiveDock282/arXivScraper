## { MODULE

##
## === DEPENDENCIES
##

## stdlib
from typing import Any

## local
from arxivscraper.support import articles, dates

##
## === SHEET CONTRACT
##

## one column per mapped field, in this order; the first sheet row is this header.
## the `arxiv_id` column is the stable key that links a sheet row to an mdfile.
SHEET_HEADER: list[str] = [
    "arxiv_id",
    "title",
    "authors",
    "abstract",
    "url_pdf",
    "category_primary",
    "category_others",
    "date_published",
    "date_updated",
    "tags",
    "status",
    "score",
    "ai_reason",
]


def header_row(
) -> list[str]:
    """Return the sheet header as a fresh list (safe to mutate)."""
    return list(SHEET_HEADER)


##
## === ARTICLE -> SHEET ROW
##


def article_to_row(
    article: articles.Article,
) -> list[str]:
    """Serialise `article` as a flat sheet row, positionally matching `SHEET_HEADER`."""
    return [
        article.arxiv_id,
        article.title,
        ", ".join(article.authors),
        article.abstract,
        article.url_pdf,
        article.category_primary,
        ", ".join(article.category_others),
        dates.as_date_string(article.date_published),
        dates.as_date_string(article.date_updated),
        " ".join(article.config_tags),
        article.task_status.value,
        "" if article.ai_rating is None else str(article.ai_rating),
        "" if article.ai_reason is None else article.ai_reason,
    ]


##
## === SHEET ROW -> ARTICLE
##


def _split_list(
    cell: str,
) -> list[str]:
    return [element.strip() for element in cell.split(",") if element.strip()]


def row_to_article(
    row: list[Any],
) -> articles.Article:
    """Parse a sheet `row` (matching `SHEET_HEADER`) and return an `Article`.

    `config_reasons` are not represented in the sheet; the caller is expected to
    merge them back in from the existing mdfile on pull.
    """
    if len(row) != len(SHEET_HEADER):
        raise ValueError(
            f"row must contain exactly {len(SHEET_HEADER)} cells; got {len(row)}.",
        )
    values = dict(zip(SHEET_HEADER, [str(cell) if cell is not None else "" for cell in row]))
    arxiv_id = values["arxiv_id"].strip()
    if not arxiv_id:
        raise ValueError("row is missing an `arxiv_id`.")
    score_text = values["score"].strip()
    reason_text = values["ai_reason"].strip()
    return articles.Article(
        title=values["title"],
        arxiv_id=arxiv_id,
        url_pdf=values["url_pdf"],
        authors=_split_list(values["authors"]),
        abstract=values["abstract"],
        date_published=dates.as_date(values["date_published"].strip()),
        date_updated=dates.as_date(values["date_updated"].strip()),
        category_primary=values["category_primary"],
        category_others=_split_list(values["category_others"]),
        config_tags=[tag for tag in values["tags"].split() if tag],
        task_status=articles.TaskStatus(values["status"].strip()),
        ai_rating=None if not score_text else float(score_text),
        ai_reason=None if not reason_text else reason_text,
        config_reasons={},
    )


##
## === MERGE ON PULL
##


def merge_pull_article(
    incoming: articles.Article,
    existing: articles.Article | None,
) -> articles.Article:
    """Merge a sheet-derived `incoming` article with an existing mdfile's `existing` article.

    The sheet is the editing surface, so non-empty sheet values win. Empty sheet cells
    never clobber populated mdfile fields, and `config_reasons` (not represented in the
    sheet) are retained from the existing mdfile. Returns `incoming` (mutated).
    """
    if existing is None:
        return incoming
    incoming.config_reasons = existing.config_reasons
    if incoming.abstract != existing.abstract:
        ## AI evidence quotes were resolved against the existing abstract; once the
        ## abstract text changes they no longer point at valid spans, so drop them.
        incoming.ai_evidence = []
    else:
        ## the sheet carries no evidence column; retain the mdfile's evidence unchanged
        incoming.ai_evidence = list(existing.ai_evidence)
    if not incoming.config_tags:
        incoming.config_tags = list(existing.config_tags)
    if incoming.ai_rating is None:
        incoming.ai_rating = existing.ai_rating
    if not incoming.ai_reason:
        incoming.ai_reason = existing.ai_reason
    return incoming


## } MODULE
