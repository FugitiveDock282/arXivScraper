## { MODULE

##
## === DEPENDENCIES
##

## stdlib
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any, TextIO

## third-party
import arxiv
import unidecode
import yaml

## local
from arxivscraper.config_paths import directories
from arxivscraper.support import dates, file_io

##
## === TASK STATUS
##


@dataclass(frozen=True)
class StatusConfig:
    """Configuration for a single task status.

    Fields
    ---
    - `md_status`:
        String written to and read from the markdown file.
    - `tui_key`:
        Keyboard shortcut used in the TUI browser.
    - `tui_description`:
        Label shown in the TUI footer.
    """

    md_status: str
    tui_key: str
    tui_description: str


class TaskStatus(Enum):
    key: str
    description: str

    def __new__(
        cls,
        config: StatusConfig,
    ) -> "TaskStatus":
        obj = object.__new__(cls)
        obj._value_ = config.md_status
        obj.key = config.tui_key
        obj.description = config.tui_description
        return obj

    PENDING = StatusConfig(
        md_status="pending",
        tui_key="p",
        tui_description="reset",
    )
    QUEUED = StatusConfig(
        md_status="queued",
        tui_key="q",
        tui_description="queue",
    )
    READ = StatusConfig(
        md_status="read",
        tui_key="r",
        tui_description="mark read",
    )
    DOWNLOAD = StatusConfig(
        md_status="download",
        tui_key="d",
        tui_description="mark download",
    )
    NA = StatusConfig(
        md_status="n/a",
        tui_key="n",
        tui_description="mark n/a",
    )
    DELETE = StatusConfig(
        md_status="delete",
        tui_key="x",
        tui_description="mark delete",
    )


@dataclass(frozen=True)
class MatchReasons:
    """Why a paper matched a search profile."""

    title_match: bool
    abstract_match: bool
    author_match: bool

    def to_list(
        self,
    ) -> list[bool]:
        return [
            self.title_match,
            self.abstract_match,
            self.author_match,
        ]

    @classmethod
    def from_list(
        cls,
        reasons: list[Any],
    ) -> "MatchReasons":
        if len(reasons) != 3:
            raise ValueError(f"`reasons` must contain exactly 3 values; got {len(reasons)}.")
        return cls(
            title_match=bool(reasons[0]),
            abstract_match=bool(reasons[1]),
            author_match=bool(reasons[2]),
        )

    @classmethod
    def from_mapping(
        cls,
        reasons: Mapping[str, Any],
    ) -> "MatchReasons":
        return cls(
            title_match=bool(reasons["title_match"]),
            abstract_match=bool(reasons["abstract_match"]),
            author_match=bool(reasons["author_match"]),
        )


@dataclass(frozen=True)
class MatchAssessment:
    """Complete assessment for whether a paper matched a search profile."""

    reasons: MatchReasons

    @property
    def is_match(
        self,
    ) -> bool:
        return any([
            self.reasons.title_match,
            self.reasons.abstract_match,
            self.reasons.author_match,
        ], )


@dataclass(frozen=True)
class EvidenceQuote:
    """A verbatim abstract fragment the AI flagged as supporting or counting against its rating.

    Fields
    ---
    - `quote`:
        A contiguous substring of the article's abstract (resolved verbatim at scoring time).
    - `effect`:
        `positive` (the passage supported the rating) or `negative` (it subtracted).
    """

    quote: str
    effect: str

    def to_dict(
        self,
    ) -> dict[str, str]:
        return {
            "quote": self.quote,
            "effect": self.effect,
        }

    @classmethod
    def from_mapping(
        cls,
        mapping: Mapping[str, Any],
    ) -> "EvidenceQuote":
        return cls(
            quote=str(mapping["quote"]),
            effect=str(mapping["effect"]),
        )


def is_supported_effect(
    effect: str,
) -> bool:
    """Return whether `effect` is a recognised evidence direction (`positive`/`negative`)."""
    return effect in ("positive", "negative")


##
## === ARTICLE DATACLASS
##


## not frozen: task_status, ai_rating, ai_reason, config_tags, and config_reasons
## are all mutated during triage and merge workflows.
@dataclass
class Article:
    """Represents a single arXiv paper and its triage state.

    Fields
    ---
    - `config_tags`:
        List of `#tag` strings, one per search config that matched this article.
    - `config_reasons`:
        Per-config match breakdown; keyed by config name (without the `config_reason_` prefix).
    - `task_status`:
        Current triage decision; updated in the TUI browser and persisted to the mdfile.
    - `ai_rating`:
        Float score assigned by the AI scorer; `None` until scored.
    - `ai_reason`:
        Short explanation from the AI scorer; `None` until scored.
    - `ai_evidence`:
        Verbatim abstract fragments flagged by the scorer, each tagged `positive`
        or `negative`; empty until scored with rationale.
    """

    title: str
    arxiv_id: str
    url_pdf: str
    authors: list[str]
    abstract: str
    date_published: date
    date_updated: date
    category_primary: str
    category_others: list[str]
    config_tags: list[str] = field(default_factory=list)
    task_status: TaskStatus = TaskStatus.PENDING
    ai_rating: float | None = None
    ai_reason: str | None = None
    ai_evidence: list[EvidenceQuote] = field(default_factory=list)
    config_reasons: dict[str, MatchReasons] = field(default_factory=dict)


##
## === HELPERS
##


def get_truncated(
    elems: list[Any],
    *,
    max_elems: int = 5,
) -> list[str]:
    """Return `elems` as strings, truncated to `max_elems` with `"..."` appended if longer."""
    truncated_elems = []
    for elem_index, elem in enumerate(elems):
        if elem_index < max_elems:
            truncated_elems.append(str(elem))
        else:
            truncated_elems.append("...")
            break
    return truncated_elems


def sanitise_text(
    text: str,
) -> str:
    """Sanitise raw arXiv text for storage: strip special characters and normalise whitespace."""
    ## adjust text for things that go wrong with Obsidian's tex-rendering
    text = text.replace("#", "")
    text = text.replace("\'", "")
    text = text.replace(":", "...")
    text = text.replace('"', "`")
    ## add spaces before and after text between two dollar signs (LaTeX math)
    text = re.sub(
        pattern=r"(\$.*?\$)",
        repl=lambda latex_match: f" {latex_match.group(1)} ",
        string=text,
    )
    ## remove any extra (eg, double) spaces that might have been added inadvertently
    text = re.sub(
        pattern=r"\s+",
        repl=" ",
        string=text,
    ).strip()
    return text


##
## === PRINT ARTICLE
##


def print_article(
    article: Article,
    *,
    num_pad_chars: int = 13,
) -> None:
    """Print a compact summary of `article` to stdout."""

    def _print_line(
        *,
        category: str,
        content: str | list[Any],
    ) -> None:
        if isinstance(content, list):
            content = ", ".join(content)
        category = f"{category}".ljust(num_pad_chars)
        print(f"{category}: {content}")

    _print_line(
        category="Title",
        content=article.title,
    )
    _print_line(
        category="PDF URL",
        content=article.url_pdf,
    )
    _print_line(
        category="Date Updated",
        content=dates.as_date_string(article.date_updated),
    )
    _print_line(
        category="Author(s)",
        content=article.authors,
    )


##
## === WRITE ARTICLE TO FILE
##


def write_article_to_file(
    file_pointer: TextIO,
    *,
    article: Article,
) -> None:
    """Serialise `article` as YAML frontmatter followed by a task-status checkbox to `file_pointer`."""
    ## prepare the YAML frontmatter
    yaml_content: dict[str, Any] = {
        "title": article.title,
        "arxiv_id": article.arxiv_id,
        "url_pdf": article.url_pdf,
        "date_published": dates.as_date_string(article.date_published),
        "date_updated": dates.as_date_string(article.date_updated),
        "category_primary": article.category_primary,
        "category_others": article.category_others or None,
        "config_tags": article.config_tags or None,
        "authors": article.authors,
        "abstract": article.abstract,
    }
    ## add optional fields
    if article.ai_rating is not None:
        yaml_content["ai_rating"] = article.ai_rating
    if article.ai_reason is not None:
        yaml_content["ai_reason"] = article.ai_reason
    if article.ai_evidence:
        yaml_content["ai_evidence"] = [quote.to_dict() for quote in article.ai_evidence]
    ## expand config_reasons back to flat config_reason_{name} keys
    for config_name, reasons in article.config_reasons.items():
        yaml_content[f"config_reason_{config_name}"] = asdict(reasons)
    ## sort the yaml content alphabetically
    sorted_yaml_content = dict(sorted(yaml_content.items()))
    ## dump the sorted YAML frontmatter to the file
    file_pointer.write("---\n")
    yaml.dump(
        data=sorted_yaml_content,
        stream=file_pointer,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    file_pointer.write("---\n")
    ## write the task status
    file_pointer.write(f" - [{article.task_status.value}] #task status\n")


def save_article(
    article: Article,
    *,
    verbose: bool = True,
    force: bool = False,
) -> None:
    """Write `article` to its mdfile, merging state from any existing file at that path."""
    file_name = article.arxiv_id + ".md"
    file_path = directories.md_files_dir / file_name
    if file_path.exists():
        existing_article = read_markdown_file(file_path)
        ## if the article has already been assessed, do not overwrite it
        if not (force) and existing_article.task_status in [TaskStatus.READ, TaskStatus.NA]:
            if existing_article.task_status == TaskStatus.READ:
                print("The following article has already been read:")
            if existing_article.task_status == TaskStatus.NA:
                print("The following article has already been marked as n/a:")
            print_article(article)
            user_input = input("Do you want to save it again? (y/N): ").strip().lower()
            print(" ")
            if not user_input.startswith("y"):
                return
        ## retain the task status
        article.task_status = existing_article.task_status
        ## merge `config_tags`: only add unique tags
        article.config_tags = list(set(article.config_tags) | set(existing_article.config_tags))
        ## retain `ai_rating` and `ai_reason` only if not already set
        if existing_article.ai_rating is not None and article.ai_rating is None:
            article.ai_rating = existing_article.ai_rating
        if existing_article.ai_reason is not None and article.ai_reason is None:
            article.ai_reason = existing_article.ai_reason
        ## retain `ai_evidence` only if the incoming article brought none
        if existing_article.ai_evidence and not article.ai_evidence:
            article.ai_evidence = list(existing_article.ai_evidence)
        ## merge `config_reasons` from existing if not already present
        for config_name, reasons in existing_article.config_reasons.items():
            if config_name not in article.config_reasons:
                article.config_reasons[config_name] = reasons
    ## overwrite the file, retaining merged state
    with open(file_path, "w") as file_pointer:
        write_article_to_file(file_pointer, article=article)
    if verbose:
        print(f"Saved: {file_path}")


##
## === BUILD ARTICLE FROM ARXIV RESULT
##


def get_article_summary(
    arxiv_article: arxiv.Result,
    *,
    config_results: Mapping[str, MatchReasons] | None = None,
    ai_results: dict[str, Any] | None = None,
    task_status: TaskStatus = TaskStatus.PENDING,
) -> Article:
    """Build an `Article` from a raw arXiv result, optionally attaching config and AI results.

    Parameters
    ---
    - `config_results`:
        Per-config match reasons; keyed by config name.
    - `ai_results`:
        Dict with `ai_rating` and `ai_reason` keys from the AI scorer.
    - `task_status`:
        Initial triage status to assign.
    """
    if config_results is None:
        config_results = {}
    if ai_results is None:
        ai_results = {}
    authors = [unidecode.unidecode(str(author)) for author in get_truncated(arxiv_article.authors)]
    other_categories = [
        sanitise_text(category)
        for category in get_truncated(arxiv_article.categories)
        if (category != arxiv_article.primary_category)
    ]
    config_tags = [f"#{key}" if ("#" not in key) else key for key in config_results.keys()]
    config_reasons = {key: reasons for key, reasons in config_results.items()}
    pdf_url: str = arxiv_article.pdf_url or ""
    return Article(
        title=sanitise_text(arxiv_article.title),
        arxiv_id=pdf_url.split("/")[-1].split("v")[0],
        url_pdf=pdf_url,
        authors=authors,
        abstract=sanitise_text(arxiv_article.summary),
        date_published=arxiv_article.published.date(),
        date_updated=arxiv_article.updated.date(),
        category_primary=arxiv_article.primary_category,
        category_others=other_categories,
        config_tags=config_tags,
        task_status=task_status,
        ai_rating=ai_results.get("ai_rating"),
        ai_reason=ai_results.get("ai_reason"),
        config_reasons=config_reasons,
    )


##
## === READ MARKDOWN FILES
##


def _ensure_frontmatter_keys(
    *,
    meta_data: dict[str, Any],
) -> None:
    required_keys = [
        "title",
        "authors",
        "abstract",
        "arxiv_id",
        "url_pdf",
        "date_published",
        "date_updated",
        "category_primary",
        "category_others",
        "config_tags",
    ]
    missing_keys = [key for key in required_keys if key not in meta_data]
    if missing_keys:
        raise ValueError(f"missing required keys in frontmatter: {', '.join(missing_keys)}.")


def read_markdown_file(
    file_path: Path,
) -> Article:
    """Parse an mdfile at `file_path` and return it as an `Article`."""
    content = file_io.read_markdown_file(file_path)
    ## split the file into frontmatter (YAML) and body (markdown)
    match = re.match(
        pattern=r"^---\n(.*?)\n---\n(.*)",
        string=content,
        flags=re.DOTALL,
    )
    if match:
        front_matter = match.group(1)
        body = match.group(2)
    else:
        raise ValueError("missing frontmatter section in the markdown file.")
    ## parse the YAML frontmatter
    try:
        meta_data = yaml.safe_load(front_matter)
    except yaml.YAMLError as error:
        raise ValueError("error parsing YAML frontmatter.") from error
    _ensure_frontmatter_keys(meta_data=meta_data)
    ## collect config_reason_* keys into a dict keyed by config name
    config_reasons = {
        key[len("config_reason_"):]:
        (MatchReasons.from_mapping(value) if isinstance(value, Mapping) else MatchReasons.from_list(value))
        for key, value in meta_data.items()
        if key.startswith("config_reason_")
    }
    ## collect any AI evidence quotes, skipping malformed entries
    ai_evidence: list[EvidenceQuote] = []
    for raw_quote in (meta_data.get("ai_evidence") or []):
        if not isinstance(raw_quote, Mapping):
            continue
        try:
            ai_evidence.append(EvidenceQuote.from_mapping(raw_quote))
        except (KeyError, TypeError, ValueError):
            continue
    ## find the character inside the brackets [] on the same line as `#task`
    task_status = TaskStatus.PENDING
    task_match = re.search(
        pattern=r"^\s*-\s+\[([^\]]+)\].*#task",
        string=body,
        flags=re.MULTILINE,
    )
    if task_match:
        try:
            task_status = TaskStatus(task_match.group(1))
        except ValueError:
            task_status = TaskStatus.PENDING
    return Article(
        title=meta_data.get("title"),
        authors=meta_data.get("authors"),
        abstract=meta_data.get("abstract"),
        arxiv_id=meta_data.get("arxiv_id"),
        url_pdf=meta_data.get("url_pdf"),
        date_published=dates.as_date(meta_data.get("date_published")),
        date_updated=dates.as_date(meta_data.get("date_updated")),
        category_primary=meta_data.get("category_primary"),
        category_others=meta_data.get("category_others") or [],
        config_tags=meta_data.get("config_tags") or [],
        ai_rating=meta_data.get("ai_rating"),
        ai_reason=meta_data.get("ai_reason"),
        ai_evidence=ai_evidence,
        task_status=task_status,
        config_reasons=config_reasons,
    )


def read_all_markdown_files() -> list[Article]:
    """Load and return all mdfiles in the output directory as `Article` objects."""
    return [read_markdown_file(file_path) for file_path in sorted(directories.md_files_dir.glob("*.md"))]


## } MODULE
