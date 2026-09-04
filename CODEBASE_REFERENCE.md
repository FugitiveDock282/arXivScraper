# arXivScraper — codebase reference

**What it is:** A lightweight paper-management CLI+TUI for finding, triaging, and scoring arXiv papers relevant to the user's research. Persists each paper as an Obsidian-friendly `.md` file under `md_files/` (one per arXiv ID), with YAML frontmatter + a `- [status] #task` checkbox.

**Stack:** Python ≥3.13, managed with `uv` (`uv sync` / `uv run`). Deps: `arxiv`, `numpy`, `openai`, `openpyxl`, `requests`, `pyyaml`, `textual` (TUI), `unidecode`. Dev: `basedpyright`, `pytest` (but tests use `unittest`). Entry point: `arxivscraper.app:main` (`src/arxivscraper/app.py:20`).

**Env:** Requires `ARXIVSCRAPER_ROOT` env var pointing at repo root — set in `config_paths/directories.py:15`, hard-fails otherwise.

**Layout:**
- `src/arxivscraper/app.py` — dispatch: `--search`(+`--score`), `--score`, `--fetch`, `--download`, `--browse`, `--retag`.
- `src/arxivscraper/config_paths/` — `directories.py` (path constants: `md_files_dir`, `pdfs_dir`, `search_configs_dir`, `ai_configs_dir`), `files.py` (AI config filenames).
- `src/arxivscraper/support/` — `articles.py`, `dates.py`, `file_io.py`, `script_cli.py`, `search_criteria.py`.
- `src/arxivscraper/workflows/` — `search_arxiv.py`, `ai_score.py`, `browse_papers.py` (Textual TUI), `download_pdfs.py`, `fetch_paper.py`, `retag.py`, `sync_sheets.py`.
- `utests/` — `test_filter.py`, `test_article_utils.py`, `test_sheet_mapping.py`, `test_local_sheet.py`, `test_ai_evidence.py`.
- `configs/` — `search/<profile>.toml`, `ai/ai_provider.toml`, `ai/user_profile.txt`, `ai/ai_guidelines.txt`, `sheets/sheets_config.toml`. Real configs are gitignored on main; use `*.example` templates.

**Code conventions:** Every module uses `## === DEPENDENCIES/... ===` section headers and a `## { MODULE` / `## } MODULE` (or `{ SCRIPT`, `{ U-TEST`) fence. Explanatory comments use `## `. basedpyright is strict; several rules suppressed in `pyproject.toml`. Command style: `uv run arxivscraper <flags>`; tests: `uv run pytest`.

**Core data model** (`support/articles.py`):
- `Article` (dataclass, mutable): title, arxiv_id (no `vNN`), url_pdf, authors (unidecoded), abstract, date_published/updated, category_primary, category_others, `config_tags` (`#tag` strings, one per matching config), `task_status`, `ai_rating` (float|None), `ai_reason` (str|None), `ai_evidence` (list of `EvidenceQuote`, each a verbatim abstract `quote` + `effect` `positive`/`negative`), `config_reasons` (dict config_name → `MatchReasons`).
- `TaskStatus` enum (value = md string): PENDING `pending`/`p`, QUEUED `queued`/`q`, READ `read`/`r`, DOWNLOAD `download`/`d`, NA `n/a`/`n`, DELETE `delete`/`x`.
- `MatchReasons`: title_match/abstract_match/author_match booleans; `MatchAssessment.is_match` = any reason true.

**md file format:** YAML frontmatter (alphabetically sorted keys; `config_reasons` flattened to `config_reason_<name>`; optional `ai_rating`/`ai_reason`/`ai_evidence` list of `{quote, effect}` dicts) + body line ` - [status] #task`. Written by `write_article_to_file` (articles.py:285), parsed by `read_markdown_file` (articles.py:450, raises on missing keys). `save_article` (articles.py:328) merges state from existing file: keeps task_status, unions config_tags, retains existing ai_rating/reason/evidence, adds missing config_reasons; prompts before overwriting READ/NA articles unless `force=True`.

**Search profile matching** (`support/search_criteria.py`): nested keyword lists, operator alternates by depth — OR at even depth, AND at odd. `check_search_criteria` → `check_any_keywords_in_text` at top, recursion flips to all/any each level. Case-insensitive substring matching. `as_set_notation` renders criteria for printing.

**Search workflow** (`workflows/search_arxiv.py`): custom `_TimeoutClient`/`_TimeoutSession` wrap `arxiv.Client` with 10s/20s connect/read timeouts, 3 retries, 3s delay, page size 100. Searches each category with `lastUpdatedDate:[start TO end]` query, sorted by last-updated, skips already-saved and duplicate ids, excludes on keywords_to_exclude (title then abstract), matches include keywords on title/abstract and tracked author last names. Existing ids are mdfile stems. Saves all new matches.

**AI scoring** (`workflows/ai_score.py`): OpenAI-compatible client. `load_provider_config` reads `ai_provider.toml` (CLI `--model`/`--base-url` override; requires `api_key` and `model`). `check_provider_reachable` does one minimal call before the loop (fail-fast). Prompts: `ai_guidelines.txt` (system), `user_profile.txt` (criteria) + title/abstract. Parses JSON `{"rating", "reason", "rationale": [{"quote", "effect"}]}` with temperature 0; strips markdown fences, sanitizes invalid JSON escapes, falls back to regex recovery (`rationale` then empty). Each rationale quote is resolved to a verbatim abstract substring by `resolve_ai_evidence`/`find_quote_span` (whitespace- and case-tolerant) and stored on the article as `ai_evidence` with effect `positive`/`negative`; unresolvable or unknown-effect quotes are dropped. Only unrated articles are scored; saves each on success.

**Browse TUI** (`workflows/browse_papers.py`): Textual app. Columns: Status, Score, Tags, Category, Date, ID, Title. Keys: `p/q/r/d/n/x` set status (writes mdfile immediately), `D` action downloads, `X` action deletions (deletes md file + removes from list), `o` open PDF, `e` edit md, `f` cycle filter, `s` search, `S` sort by AI score (unscored sort as -1), `escape` quit. Abstract panel shows details incl. score+reason.

**Download** (`workflows/download_pdfs.py`): streams PDFs for `DOWNLOAD`-status articles to `pdfs/`, then resets status to PENDING. Uses default `requests.get` (no timeout set).

**Fetch** (`workflows/fetch_paper.py`): fetches one id (`^\d{4}\.\d{4,5}$`), confirms, asks for a tag (no spaces), saves as title-only match.

**Retag** (`workflows/retag.py`): re-evaluates every saved article against all search configs, recomputes `#<config>` tags (title/abstract only, excludes excluded keywords), preserves editorial tags not tied to a config, saves only changed articles.

**Sheets sync** (`workflows/sync_sheets.py`): mdfiles are the source of truth; a local `.xlsx` workbook (`configs/sheets/papers.xlsx` by default) is a view + editing surface you open in Excel/LibreOffice. `--sync` pulls then pushes per `sync_mode` (`push`/`pull`/`bidirectional`). Config is `configs/sheets/sheets_config.toml` (`spreadsheet_path`, `sheet_name`, `sync_mode`; relative paths resolve against `configs/sheets/`). The workbook/tab is read and written by `LocalSpreadsheet` in `support/local_sheet.py` — it renders cells as text (dates/floats/empties normalised), ignores style-only cells when computing the grid, and pushes values in place so manual formatting (bold headers, fills, widths) survives a rewrite. Push rewrites the data area (`article_to_row` rows), clearing content that fell out of bounds but never touching formatting; abstract cells with `ai_evidence` are written as rich text via `render_abstract_cell`, colouring positive quotes green (`FF00B050`) and negative quotes red (`FFC00000`), and openpyxl flattens rich text back to plain strings on read so pulls round-trip losslessly. Pull reads rows → `row_to_article`, merges via `merge_pull_article` (sheet value wins unless empty — empty cells never clobber populated md fields; `config_reasons` and `ai_evidence` retained from md, with evidence dropped when the abstract text changed), skips malformed rows with a count, leaves md files without a sheet row untouched. Mapping contract + merge in `support/sheet_mapping.py` (`SHEET_HEADER`: arxiv_id → ai_reason).

**Config formats:**
- `search/<name>.toml` required keys: `authors`, `categories`, `keywords_to_exclude`, `keywords_to_include`.
- `ai/ai_provider.toml`: `base_url`, `api_key`, `model`; local servers use placeholder key (e.g. `ollama`).
- `sheets/sheets_config.toml`: `spreadsheet_path` (path to a local `.xlsx` workbook; relative paths resolve against `configs/sheets/`); `sheet_name` (default `Papers`); `sync_mode` (default `bidirectional`).

**Tests:** pure unit tests (no network mocking); keyword logic in `test_filter.py`, sanitise/truncate/roundtrip/merge in `test_article_utils.py`, sheet row roundtrip + pull-merge in `test_sheet_mapping.py`, local `.xlsx` store roundtrip + cell rendering in `test_local_sheet.py`, evidence parse/quote-resolution/roundtrip/highlight-push in `test_ai_evidence.py`. Roundtrip tests assert md write→read is lossless across all fields and statuses.
