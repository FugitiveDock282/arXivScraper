## { MODULE

##
## === DEPENDENCIES
##

## stdlib
import os
from pathlib import Path

##
## === DIRECTORIES
##

_env_root = os.environ.get("ARXIVSCRAPER_ROOT")
if not _env_root:
    raise RuntimeError(
        "ARXIVSCRAPER_ROOT is not set. "
        "Add `export ARXIVSCRAPER_ROOT=/path/to/arXivScraper` to your shell profile.",
    )

PROJECT_ROOT = Path(_env_root).resolve()
configs_dir = PROJECT_ROOT / "configs"
search_configs_dir = configs_dir / "search"
ai_configs_dir = configs_dir / "ai"
sheets_configs_dir = configs_dir / "sheets"
md_files_dir = PROJECT_ROOT / "md_files"
pdfs_dir = PROJECT_ROOT / "pdfs"

## } MODULE
