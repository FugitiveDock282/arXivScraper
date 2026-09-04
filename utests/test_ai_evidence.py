## { U-TEST

##
## === DEPENDENCIES
##

## stdlib
import datetime
import io
import json
import pathlib
import shutil
import sys
import tempfile
import unittest
from typing import Any

## third-party
import openpyxl

## local
from arxivscraper.config_paths import directories
from arxivscraper.support import articles, local_sheet, sheet_mapping
from arxivscraper.workflows import ai_score, sync_sheets

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
        authors=["Author A"],
        abstract=(
            "The study demonstrates strong capture efficiency through the new model "
            "but suffers from weak robustness in practice."
        ),
        date_published=datetime.date(2000, 1, 1),
        date_updated=datetime.date(2000, 1, 2),
        category_primary="cat.AA",
        category_others=[],
        config_tags=[],
        task_status=articles.TaskStatus.PENDING,
        ai_rating=None,
        ai_reason=None,
        config_reasons={},
    )
    defaults.update(kwargs)
    return articles.Article(**defaults)


def _roundtrip(
    *,
    article: articles.Article,
) -> articles.Article:
    """Write an Article to a string buffer and read it back."""
    buffer = io.StringIO()
    articles.write_article_to_file(
        buffer,
        article=article,
    )
    md_text = buffer.getvalue()
    with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".md",
            delete=False,
    ) as file_pointer:
        file_pointer.write(md_text)
        tmp_path = pathlib.Path(file_pointer.name)
    try:
        return articles.read_markdown_file(tmp_path)
    finally:
        tmp_path.unlink()


##
## === TEST SUITE
##


class TestParseLlmJson(unittest.TestCase):

    def test_plain_json_parses(
        self,
    ) -> None:
        parsed = ai_score.parse_llm_json(
            json.dumps({"rating": 7.5, "reason": "a reason."}),
        )
        self.assertAlmostEqual(
            first=parsed["rating"],
            second=7.5,
        )
        self.assertEqual(
            first=parsed["reason"],
            second="a reason.",
        )
        self.assertEqual(
            first=parsed["rationale"],
            second=[],
        )

    def test_rationale_parsed(
        self,
    ) -> None:
        payload = {
            "rating": 8.0,
            "reason": "Core match.",
            "rationale": [
                {"quote": "strong capture efficiency", "effect": "positive"},
                {"quote": "weak robustness", "effect": "negative"},
            ],
        }
        parsed = ai_score.parse_llm_json(json.dumps(payload))
        self.assertEqual(
            first=parsed["rationale"],
            second=payload["rationale"],
        )

    def test_missing_rationale_defaults_empty(
        self,
    ) -> None:
        parsed = ai_score.parse_llm_json('{"rating": 5, "reason": "ok"}')
        self.assertEqual(
            first=parsed["rationale"],
            second=[],
        )

    def test_fenced_json_stripped(
        self,
    ) -> None:
        payload = '```json\n{"rating": 6, "reason": "ok", "rationale": []}\n```'
        parsed = ai_score.parse_llm_json(payload)
        self.assertAlmostEqual(
            first=parsed["rating"],
            second=6,
        )

    def test_none_reason_becomes_empty(
        self,
    ) -> None:
        parsed = ai_score.parse_llm_json('{"rating": 4, "reason": null}')
        self.assertEqual(
            first=parsed["reason"],
            second="",
        )

    def test_missing_rating_raises(
        self,
    ) -> None:
        with self.assertRaises(Exception):
            ai_score.parse_llm_json('{"reason": "no rating"}')

    def test_malformed_json_raises(
        self,
    ) -> None:
        with self.assertRaises(Exception):
            ai_score.parse_llm_json('not json at all')


class TestFindQuoteSpan(unittest.TestCase):

    def test_exact_match(
        self,
    ) -> None:
        abstract = "The study shows strong capture efficiency."
        self.assertEqual(
            first=ai_score.find_quote_span(abstract, "strong capture"),
            second="strong capture",
        )

    def test_whitespace_differences_tolerated(
        self,
    ) -> None:
        abstract = "one  two\nthree four"
        self.assertEqual(
            first=ai_score.find_quote_span(abstract, "one two\nthree"),
            second="one  two\nthree",
        )

    def test_case_insensitive_fallback(
        self,
    ) -> None:
        abstract = "The Study Shows Efficiency"
        self.assertEqual(
            first=ai_score.find_quote_span(abstract, "study shows"),
            second="Study Shows",
        )

    def test_punctuation_contiguous(
        self,
    ) -> None:
        abstract = "We use, however, a spectral method."
        self.assertEqual(
            first=ai_score.find_quote_span(abstract, "use, however,"),
            second="use, however,",
        )

    def test_no_match_returns_none(
        self,
    ) -> None:
        abstract = "The study shows efficiency."
        self.assertIsNone(ai_score.find_quote_span(abstract, "something else"))

    def test_empty_quote_returns_none(
        self,
    ) -> None:
        self.assertIsNone(ai_score.find_quote_span("an abstract.", ""))

    def test_quote_longer_than_abstract_returns_none(
        self,
    ) -> None:
        self.assertIsNone(ai_score.find_quote_span("short", "a very long quote here indeed"))


class TestResolveAiEvidence(unittest.TestCase):

    def test_resolves_and_normalises_quotes(
        self,
    ) -> None:
        abstract = "one  two\nthree four"
        evidence = ai_score.resolve_ai_evidence(
            abstract=abstract,
            rationale=[
                {"quote": "one two three", "effect": "positive"},
            ],
        )
        self.assertEqual(
            first=[quote.to_dict() for quote in evidence],
            second=[{"quote": "one  two\nthree", "effect": "positive"}],
        )

    def test_unknown_effect_dropped(
        self,
    ) -> None:
        evidence = ai_score.resolve_ai_evidence(
            abstract="a b c",
            rationale=[
                {"quote": "a", "effect": "maybe"},
            ],
        )
        self.assertEqual(
            first=evidence,
            second=[],
        )

    def test_unresolvable_quote_dropped(
        self,
    ) -> None:
        evidence = ai_score.resolve_ai_evidence(
            abstract="a b c",
            rationale=[
                {"quote": "never appears", "effect": "positive"},
            ],
        )
        self.assertEqual(
            first=evidence,
            second=[],
        )

    def test_non_dict_items_dropped(
        self,
    ) -> None:
        evidence = ai_score.resolve_ai_evidence(
            abstract="a b c",
            rationale=["not-a-dict", None],
        )
        self.assertEqual(
            first=evidence,
            second=[],
        )

    def test_duplicate_pairs_deduplicated(
        self,
    ) -> None:
        evidence = ai_score.resolve_ai_evidence(
            abstract="a b c",
            rationale=[
                {"quote": "a", "effect": "positive"},
                {"quote": "a", "effect": "positive"},
            ],
        )
        self.assertEqual(
            first=len(evidence),
            second=1,
        )


class TestEvidenceArticle_Roundtrip(unittest.TestCase):

    def test_evidence_roundtrip_lossless(
        self,
    ) -> None:
        evidence = [
            articles.EvidenceQuote(quote="strong capture efficiency", effect="positive"),
            articles.EvidenceQuote(quote="weak robustness", effect="negative"),
        ]
        original = _make_article(
            ai_rating=7.5,
            ai_reason="a reason.",
            ai_evidence=evidence,
        )
        restored = _roundtrip(article=original)
        self.assertEqual(
            first=[quote.to_dict() for quote in restored.ai_evidence],
            second=[quote.to_dict() for quote in evidence],
        )

    def test_empty_evidence_roundtrip(
        self,
    ) -> None:
        original = _make_article(ai_rating=6.0)
        restored = _roundtrip(article=original)
        self.assertEqual(
            first=restored.ai_evidence,
            second=[],
        )

    def test_malformed_evidence_skipped(
        self,
    ) -> None:
        md_text = (
            "---\ntitle: t\narxiv_id: 0000.00000\nurl_pdf: u\n"
            'date_published: "2000-01-01"\ndate_updated: "2000-01-02"\n'
            "category_primary: c\ncategory_others: null\nconfig_tags: null\n"
            "authors: [A]\nabstract: abc\nai_evidence:\n- quote: ok\n  effect: positive\n"
            "- {bad: entry}\n- just-a-string\n---\n - [pending] #task\n"
        )
        with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".md",
                delete=False,
        ) as file_pointer:
            file_pointer.write(md_text)
            tmp_path = pathlib.Path(file_pointer.name)
        try:
            article = articles.read_markdown_file(tmp_path)
        finally:
            tmp_path.unlink()
        self.assertEqual(
            first=[quote.to_dict() for quote in article.ai_evidence],
            second=[{"quote": "ok", "effect": "positive"}],
        )


class TestEvidenceMerge_Cases(unittest.TestCase):

    def test_same_abstract_retains_evidence(
        self,
    ) -> None:
        evidence = [
            articles.EvidenceQuote(quote="strong capture", effect="positive"),
        ]
        existing = _make_article(ai_evidence=evidence)
        incoming = _make_article()
        merged = sheet_mapping.merge_pull_article(incoming, existing)
        self.assertEqual(
            first=[quote.to_dict() for quote in merged.ai_evidence],
            second=[quote.to_dict() for quote in evidence],
        )

    def test_changed_abstract_drops_evidence(
        self,
    ) -> None:
        existing = _make_article(ai_evidence=[
            articles.EvidenceQuote(quote="strong capture", effect="positive"),
        ])
        incoming = _make_article(abstract="a completely different abstract now.")
        merged = sheet_mapping.merge_pull_article(incoming, existing)
        self.assertEqual(
            first=merged.ai_evidence,
            second=[],
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


class TestRenderAbstractCell(unittest.TestCase):

    def test_no_highlights_returns_plain_text(
        self,
    ) -> None:
        abstract = "just an abstract with no highlights."
        cell = local_sheet.render_abstract_cell(abstract, [])
        self.assertEqual(
            first=cell,
            second=abstract,
        )

    def test_unresolvable_quotes_leave_plain_text(
        self,
    ) -> None:
        abstract = "just an abstract."
        cell = local_sheet.render_abstract_cell(abstract, [("missing", "positive")])
        self.assertEqual(
            first=cell,
            second=abstract,
        )

    def test_highlighted_cell_concatenates_to_abstract(
        self,
    ) -> None:
        abstract = "The study shows strong capture efficiency but weak robustness."
        cell = local_sheet.render_abstract_cell(abstract, [
            ("strong capture efficiency", "positive"),
            ("weak robustness", "negative"),
        ])
        self.assertEqual(
            first=str(cell),
            second=abstract,
        )
        colored = [part for part in cell if not isinstance(part, str)]
        self.assertEqual(
            first=len(colored),
            second=2,
        )
        colors = set()
        for part in colored:
            color = part.font.color
            self.assertIsNotNone(color)
            assert color is not None
            colors.add(color.rgb)
        self.assertIn(
            member="FF00B050",
            container=colors,
        )
        self.assertIn(
            member="FFC00000",
            container=colors,
        )


class TestHighlight_PushWorkflow(unittest.TestCase):
    """A push renders the abstract column with coloured runs for evidence-bearing articles."""

    def setUp(
        self,
    ) -> None:
        self._temp_dir = tempfile.mkdtemp()
        self._md_dir = pathlib.Path(self._temp_dir) / "md_files"
        self._md_dir.mkdir()
        self._previous_md_dir = directories.md_files_dir
        directories.md_files_dir = self._md_dir

    def tearDown(
        self,
    ) -> None:
        directories.md_files_dir = self._previous_md_dir
        shutil.rmtree(self._temp_dir)

    def test_push_colours_evidence_abstracts_only(
        self,
    ) -> None:
        abstract = (
            "The study shows strong capture efficiency through the new model "
            "but suffers from weak robustness in practice."
        )
        evidence = [
            articles.EvidenceQuote(quote="strong capture efficiency", effect="positive"),
            articles.EvidenceQuote(quote="weak robustness", effect="negative"),
        ]
        with_evidence = _make_article(
            arxiv_id="0001.00001",
            abstract=abstract,
            ai_rating=8.0,
            ai_evidence=evidence,
        )
        without_evidence = _make_article(
            arxiv_id="0002.00002",
            abstract=abstract,
            ai_rating=3.0,
            ai_evidence=[],
        )
        for article in (with_evidence, without_evidence):
            with open(self._md_dir / f"{article.arxiv_id}.md", "w") as file_pointer:
                articles.write_article_to_file(file_pointer, article=article)
        workbook_path = pathlib.Path(self._temp_dir) / "papers.xlsx"
        sync_sheets.push_to_sheets(config={
            "spreadsheet_path": workbook_path,
            "sheet_name": "Papers",
        })
        workbook = openpyxl.load_workbook(workbook_path, rich_text=True)
        worksheet = workbook["Papers"]
        abstract_column = sheet_mapping.SHEET_HEADER.index("abstract")
        cells = {}
        for row in worksheet.iter_rows(min_row=2, values_only=False):
            cells[row[0].value] = row[abstract_column].value
        self.assertIsInstance(cells["0001.00001"], list)
        self.assertEqual(
            first=str(cells["0001.00001"]),
            second=abstract,
        )
        colored = [part for part in cells["0001.00001"] if not isinstance(part, str)]
        self.assertEqual(
            first=len(colored),
            second=2,
        )
        self.assertIsInstance(cells["0002.00002"], str)


##
## === ENTRY POINT
##

if __name__ == "__main__":
    unittest.main()
    sys.exit(0)

## } U-TEST
