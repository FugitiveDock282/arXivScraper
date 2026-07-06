# arXivScraper

**arxivscraper** is a lightweight paper management tool for finding and managing arXiv papers that are relevant for you.

![TUI browser](./example-tui.png?v=2)

---

## Installation

1. Clone the repository:

```bash
git clone --single-branch https://github.com/AstroKriel/arXivScraper.git
cd arXivScraper
```

2. Install dependencies:

```bash
uv sync
```

3. Set the `ARXIVSCRAPER_ROOT` environment variable to the repo path. Add this to your shell profile (`~/.zshrc`, `~/.bashrc`, etc.):

```bash
export ARXIVSCRAPER_ROOT=/path/to/arXivScraper
```

4. Optional: install as a system-wide `uv` tool so `arxivscraper` is available from anywhere:

```bash
uv tool install . --no-cache
```

This adds `arxivscraper` to your `PATH`, so you can run:

```bash
arxivscraper --browse
arxivscraper --search --config-name <profile> --lookback-days <n>
arxivscraper --score
arxivscraper --retag
arxivscraper --fetch -id <arxiv-id>
arxivscraper --download
```

---

## Workflow

### Search

Search arXiv for papers matching a search profile. The search window is based on arXiv submission date:

```bash
uv run arxivscraper --search --config-name <profile> --lookback-days <n> [--from-date YYYY-MM-DD]
```

Papers are saved as markdown files in `md_files/`. If `--config-name` or `--lookback-days` are not passed, the script will prompt for them. By default, the lookback window ends on today; pass `--from-date` to anchor it to a different date.

### Browse

Open the terminal interface browser to read abstracts and triage saved papers (see the picture above):

```bash
uv run arxivscraper --browse
```

| Key | State |
|---|---|
| `p` | pending (default) |
| `q` | queued |
| `r` | read |
| `d` | mark for download |
| `D` | action downloads |
| `n` | n/a (article is not relevant for you) |
| `x` | mark for deletion |
| `X` | action deletions |
| `o` | open PDF in browser |
| `e` | open markdown file in the default editor |
| `f` | cycle filter between `p`, `q`, `r`, `d`, `n`, and `x` states |
| `s` | toggle text search |
| `S` | toggle sort between date and AI score |
| `escape` | quit |

### Score

Score all unrated papers using an AI provider:

```bash
uv run arxivscraper --score
```

Pass `--model <model>` or `--base-url <url>` to override the values in `configs/ai/ai_provider.toml`.

### Retag

Re-evaluate all search config filters against every saved paper, adding or removing tags to reflect the current config state:

```bash
uv run arxivscraper --retag
```

Run this after adding or modifying a search profile to backfill tags without re-running a full search.

### Fetch

Fetch a specific paper by arXiv ID:

```bash
uv run arxivscraper --fetch -id <arxiv-id>
```

The script displays the title, authors, and abstract for confirmation before saving.

### Download

From the terminal interface browser, press `d` to mark a paper for download. Use `f` to cycle the filter to `download` to review which papers are queued before pressing `D` to action the download. Downloaded papers return them back to a `pending` (`p`) state.

Alternatively, you can also run the download step directly from the terminal:

```bash
uv run arxivscraper --download
```

---

## Configuration

| File | Purpose |
|---|---|
| `configs/search/<profile>.toml` | search criteria for one topic |
| `configs/ai/ai_provider.toml` | optional AI provider settings (model, API key, base URL) |
| `configs/ai/user_profile.txt` | scoring criteria sent to the AI |
| `configs/ai/ai_guidelines.txt` | system prompt rules for AI scoring |

`configs/search/*.toml`, `configs/ai/user_profile.txt`, and `configs/ai/ai_provider.toml` hold personal data (your research topics, credentials) and are gitignored on `main`. Copy the matching `*.example` file to get started, or keep your real configs on a personal branch (e.g. `username/config`) rebased on `main`.

### Search profiles

Each `.toml` file in `configs/search/` defines one search profile. Copy `configs/search/example.toml` to `<profile>.toml` and pass the filename without extension as `--config-name`.

```toml
authors = []
categories = ["<arxiv-category>"]
keywords_to_exclude = ["<keyword-a>"]
keywords_to_include = ["<keyword-b>", ["<keyword-c>", "<keyword-d>"]]
```

Keywords use a nested list notation where the operator alternates every level: OR at even depth, AND at odd depth.

| Depth | Operator |
|---|---|
| 0 (top-level) | OR |
| 1 (nested) | AND |
| 2 (doubly-nested) | OR |
| ... | ... |

```toml
keywords = [
    "<keyword-a>",
    ["<keyword-b>", ["<keyword-c>", "<keyword-d>"]],
]
```

Matches: `<keyword-a>` OR (`<keyword-b>` AND (`<keyword-c>` OR `<keyword-d>`))

See `utests/test_filter.py` for examples in action.

### AI provider

Copy `configs/ai/ai_provider.example.toml` to `configs/ai/ai_provider.toml` and fill in your values. Supports OpenAI, Anthropic, Ollama, and any OpenAI-compatible API.

### User profile

Copy `configs/ai/user_profile.example.txt` to `configs/ai/user_profile.txt` and describe your research interests. This text is sent directly to the AI as scoring criteria.

---

## License

This project is licensed under the MIT License; see [LICENSE](./LICENSE.md) for details.
