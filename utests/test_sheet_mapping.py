## { U-TEST

##
## === DEPENDENCIES
##

## stdlib
import datetime
import sys
import unittest
from typing import Any

## local
from arxivscraper.support import articles, sheet_mapping

##
## === HELPERS
##


def _make_article(
    **kwargs: Any,
) -> articles.Article:
    defaults: dict[str, Any] = dict(
        title="sample title",
        arxiv_id="0000.00000",
        url_pdf="https://arxiv.org/pdf/0000.00000",
        authors=["Author A", "Author B"],
        abstract="sample abstract text.",
        date_published=datetime.date(2000, 1, 1),
        date_updated=datetime.date(2000, 1, 2),
        category_primary="cat.AA",
        category_others=["cat.BB"],
        config_tags=["#tag-a"],
        task_status=articles.TaskStatus.PENDING,
        ai_rating=None,
        ai_reason=None,
        config_reasons={
            "tag-a": articles.MatchReasons(
                title_match=True,
                abstract_match=False,
                author_match=True,
            ),
        },
    )
    defaults.update(kwargs)
    return articles.Article(**defaults)


##
## === TEST SUITE
##


class TestArticleToRow_Cases(unittest.TestCase):

    def test_full_article(
        self,
    ) -> None:
        article = _make_article(
            ai_rating=7.5,
            ai_reason="a reason.",
        )
        row = sheet_mapping.article_to_row(article)
        self.assertEqual(
            first=row[sheet_mapping.SHEET_HEADER.index("arxiv_id")],
            second="0000.00000",
        )
        self.assertEqual(
            first=row[sheet_mapping.SHEET_HEADER.index("authors")],
            second="Author A, Author B",
        )
        self.assertEqual(
            first=row[sheet_mapping.SHEET_HEADER.index("tags")],
            second="#tag-a",
        )
        self.assertEqual(
            first=row[sheet_mapping.SHEET_HEADER.index("status")],
            second="pending",
        )
        self.assertEqual(
            first=row[sheet_mapping.SHEET_HEADER.index("score")],
            second="7.5",
        )
        self.assertEqual(
            first=row[sheet_mapping.SHEET_HEADER.index("date_published")],
            second="2000-01-01",
        )

    def test_unset_optional_fields_are_empty(
        self,
    ) -> None:
        article = _make_article(
            category_others=[],
            config_tags=[],
            ai_rating=None,
            ai_reason=None,
        )
        row = sheet_mapping.article_to_row(article)
        self.assertEqual(
            first=row[sheet_mapping.SHEET_HEADER.index("category_others")],
            second="",
        )
        self.assertEqual(
            first=row[sheet_mapping.SHEET_HEADER.index("tags")],
            second="",
        )
        self.assertEqual(
            first=row[sheet_mapping.SHEET_HEADER.index("score")],
            second="",
        )
        self.assertEqual(
            first=row[sheet_mapping.SHEET_HEADER.index("ai_reason")],
            second="",
        )


class TestRowToArticle_Cases(unittest.TestCase):

    def test_invalid_row_length_raises(
        self,
    ) -> None:
        with self.assertRaises(ValueError):
            sheet_mapping.row_to_article(["a", "b"])

    def test_missing_arxiv_id_raises(
        self,
    ) -> None:
        row = [""] * len(sheet_mapping.SHEET_HEADER)
        with self.assertRaises(ValueError):
            sheet_mapping.row_to_article(row)


class TestSheetMapping_Roundtrip(unittest.TestCase):
    """Checks that article_to_row + row_to_article is lossless for all mapped fields."""

    def test_full_roundtrip(
        self,
    ) -> None:
        original = _make_article(
            ai_rating=7.5,
            ai_reason="a reason.",
        )
        restored = sheet_mapping.row_to_article(sheet_mapping.article_to_row(original))
        self.assertEqual(
            first=restored.title,
            second=original.title,
        )
        self.assertEqual(
            first=restored.arxiv_id,
            second=original.arxiv_id,
        )
        self.assertEqual(
            first=restored.url_pdf,
            second=original.url_pdf,
        )
        self.assertEqual(
            first=restored.authors,
            second=original.authors,
        )
        self.assertEqual(
            first=restored.abstract,
            second=original.abstract,
        )
        self.assertEqual(
            first=restored.date_published,
            second=original.date_published,
        )
        self.assertEqual(
            first=restored.date_updated,
            second=original.date_updated,
        )
        self.assertEqual(
            first=restored.category_primary,
            second=original.category_primary,
        )
        self.assertEqual(
            first=restored.category_others,
            second=original.category_others,
        )
        self.assertEqual(
            first=restored.config_tags,
            second=original.config_tags,
        )
        self.assertEqual(
            first=restored.task_status,
            second=original.task_status,
        )
        self.assertIsNotNone(restored.ai_rating)
        assert restored.ai_rating is not None
        self.assertAlmostEqual(
            first=restored.ai_rating,
            second=7.5,
        )
        self.assertEqual(
            first=restored.ai_reason,
            second=original.ai_reason,
        )

    def test_empty_optionals_roundtrip(
        self,
    ) -> None:
        original = _make_article(
            category_others=[],
            config_tags=[],
            ai_rating=None,
            ai_reason=None,
        )
        restored = sheet_mapping.row_to_article(sheet_mapping.article_to_row(original))
        self.assertEqual(
            first=restored.category_others,
            second=[],
        )
        self.assertEqual(
            first=restored.config_tags,
            second=[],
        )
        self.assertIsNone(restored.ai_rating)
        self.assertIsNone(restored.ai_reason)

    def test_status_roundtrip(
        self,
    ) -> None:
        for status in [
                articles.TaskStatus.PENDING,
                articles.TaskStatus.QUEUED,
                articles.TaskStatus.READ,
                articles.TaskStatus.DOWNLOAD,
                articles.TaskStatus.NA,
                articles.TaskStatus.DELETE,
        ]:
            with self.subTest(status=status):
                original = _make_article(task_status=status)
                restored = sheet_mapping.row_to_article(sheet_mapping.article_to_row(original))
                self.assertEqual(
                    first=restored.task_status,
                    second=status,
                )


class TestMergePullArticle_Cases(unittest.TestCase):
    """Checks the sheet->md merge rule: non-empty sheet values win, empty ones keep md."""

    def test_empty_sheet_cells_keep_md_values(
        self,
    ) -> None:
        existing = _make_article(
            ai_rating=8.0,
            ai_reason="keep me.",
            config_tags=["#tag-a"],
        )
        incoming = _make_article(
            ai_rating=None,
            ai_reason=None,
            config_tags=[],
        )
        merged = sheet_mapping.merge_pull_article(incoming, existing)
        self.assertIsNotNone(merged.ai_rating)
        assert merged.ai_rating is not None
        self.assertAlmostEqual(
            first=merged.ai_rating,
            second=8.0,
        )
        self.assertEqual(
            first=merged.ai_reason,
            second="keep me.",
        )
        self.assertEqual(
            first=merged.config_tags,
            second=["#tag-a"],
        )

    def test_populated_sheet_values_win(
        self,
    ) -> None:
        existing = _make_article(
            ai_rating=8.0,
            ai_reason="old",
            config_tags=["#tag-a"],
        )
        incoming = _make_article(
            ai_rating=9.5,
            ai_reason="new",
            config_tags=["#tag-b"],
        )
        merged = sheet_mapping.merge_pull_article(incoming, existing)
        self.assertIsNotNone(merged.ai_rating)
        assert merged.ai_rating is not None
        self.assertAlmostEqual(
            first=merged.ai_rating,
            second=9.5,
        )
        self.assertEqual(
            first=merged.ai_reason,
            second="new",
        )
        self.assertEqual(
            first=merged.config_tags,
            second=["#tag-b"],
        )

    def test_config_reasons_retained_from_existing(
        self,
    ) -> None:
        existing = _make_article(
            config_reasons={
                "tag-a": articles.MatchReasons(
                    title_match=True,
                    abstract_match=False,
                    author_match=False,
                ),
            },
        )
        incoming = _make_article(config_reasons={})
        merged = sheet_mapping.merge_pull_article(incoming, existing)
        self.assertEqual(
            first=merged.config_reasons,
            second=existing.config_reasons,
        )

    def test_no_existing_returns_incoming(
        self,
    ) -> None:
        incoming = _make_article()
        merged = sheet_mapping.merge_pull_article(incoming, None)
        self.assertIs(
            merged,
            incoming,
        )


##
## === ENTRY POINT
##

if __name__ == "__main__":
    unittest.main()
    sys.exit(0)

## } U-TEST
