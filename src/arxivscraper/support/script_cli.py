## { MODULE

##
## === DEPENDENCIES
##

## stdlib
import argparse
import re
from typing import Any

## local
from arxivscraper.config_paths import directories
from arxivscraper.support import dates

##
## === USER INPUT HANDLER
##


class CLIParser:
    """Parse and validate CLI arguments for the main program, search, score, and fetch modes."""

    def __init__(
        self,
        *,
        include_main: bool = False,
        include_search: bool = False,
        include_fetch: bool = False,
        include_score: bool = False,
    ) -> None:
        self.parser = argparse.ArgumentParser(
            description="arXiv-Scraper: program to search for relevant arXiv papers.",
            formatter_class=lambda prog: argparse.RawDescriptionHelpFormatter(
                prog=prog,
                max_help_position=50,
            ),
        )
        if include_main:
            self._add_main_program_arguments()
        if include_search:
            self._add_search_arguments()
        if include_fetch:
            self._add_fetch_argument()
        if include_score:
            self._add_score_arguments()
        ## parse and store arguments
        name_space, _ = self.parser.parse_known_args()
        self.args = vars(name_space)

    def _add_main_program_arguments(
        self,
    ) -> None:
        """Add main program flag arguments."""
        parse_flags = self.parser.add_argument_group(description="Main program flags:")
        for short_flag, long_flag in [
            ("-s", "--search"),
            ("-f", "--fetch"),
            ("-r", "--score"),
            ("-b", "--browse"),
            ("-d", "--download"),
            ("-t", "--retag"),
            ("-y", "--sync"),
        ]:
            parse_flags.add_argument(
                short_flag,
                long_flag,
                default=False,
                required=False,
                action="store_true",
                help="Type: bool, default: %(default)s",
            )

    def _add_search_arguments(
        self,
    ) -> None:
        """Add search-specific arguments."""
        search_args = self.parser.add_argument_group(
            description="Search arguments (relevant when main program is run with `-s`):",
        )
        search_args.add_argument(
            "-c",
            "--config-name",
            type=str,
            required=False,
            metavar="",
            dest="config_name",
            help="Name of the config-file that defines search parameters.",
        )
        search_args.add_argument(
            "-lb",
            "--lookback-days",
            type=int,
            required=False,
            metavar="",
            dest="lookback_days",
            help="Lookback period (in days) to start search.",
        )
        search_args.add_argument(
            "-fd",
            "--from-date",
            type=str,
            required=False,
            metavar="",
            dest="from_date",
            help="End date for the lookback window in `YYYY-MM-DD` format.",
        )

    def _add_fetch_argument(
        self,
    ) -> None:
        """Add fetch-specific arguments."""
        fetch_args = self.parser.add_argument_group(
            description="Fetch argument (relevant when running with `-f`):",
        )
        fetch_args.add_argument(
            "-id",
            type=str,
            required=False,
            metavar="",
            help="arXiv ID in the format `2310.17036`.",
        )

    def _add_score_arguments(
        self,
    ) -> None:
        """Add score-specific arguments."""
        score_args = self.parser.add_argument_group(
            description="Score arguments (relevant when running with `-r`):",
        )
        score_args.add_argument(
            "--model",
            type=str,
            required=False,
            metavar="",
            help="Model name override. Overrides configs/ai/ai_provider.toml.",
        )
        score_args.add_argument(
            "--base-url",
            type=str,
            required=False,
            metavar="",
            dest="base_url",
            help="API base URL override. Overrides configs/ai/ai_provider.toml.",
        )
        score_args.add_argument(
            "--rescore",
            action="store_true",
            required=False,
            default=False,
            help="Also re-score articles that already have a rating.",
        )

    def get_program_inputs(
        self,
    ) -> dict[str, Any]:
        """Return main program flags; ensure at least one is set."""
        main_flags = ["search", "fetch", "score", "browse", "download", "retag", "sync"]
        if not any(self.args.get(flag) for flag in main_flags):
            print(
                "Error: At least one of the following flags must be provided: --search, --fetch, --score, --browse, --download, --retag, --sync\n",
            )
            self.parser.print_help()
        return {key: self.args.get(key) for key in ["search", "fetch", "score", "browse", "download", "retag", "sync"]}

    def get_search_inputs(
        self,
    ) -> dict[str, Any]:
        """Return search-specific arguments; prompt for any missing required parameters."""
        search_args = {
            key: self.args.get(key)
            for key in [
                "config_name",
                "lookback_days",
                "from_date",
            ]
        }
        if not search_args["config_name"]:
            search_args["config_name"] = input("Please provide --config-name: ")
        config_name = search_args["config_name"]
        config_path = directories.search_configs_dir / f"{config_name}.toml"
        if not config_path.exists():
            raise FileNotFoundError(
                f"config file not found: `{config_name}.toml`; searched in {directories.search_configs_dir}.",
            )
        if search_args["lookback_days"] is None:
            search_args["lookback_days"] = int(input("Please provide --lookback-days: "))
        if search_args["from_date"] is not None:
            search_args["from_date"] = dates.as_datetime(
                dates.as_date(search_args["from_date"]),
            )
        return search_args

    def get_score_inputs(
        self,
    ) -> dict[str, Any]:
        """Return score-specific CLI overrides; `None` values mean 'use config file'."""
        return {key: self.args.get(key) for key in ["model", "base_url", "rescore"]}

    def get_fetch_inputs(
        self,
    ) -> str:
        """Return the fetch arXiv ID; prompt if not passed and validate the format."""
        arxiv_id = self.args.get("id")
        if arxiv_id is None:
            print("Which article do you want to fetch from the arXiv?")
            arxiv_id = input("Enter an arXiv ID (e.g., `2310.17036`): ")
        print(" ")
        re_pattern = r"^\d{4}\.\d{4,5}$"
        if not re.match(
                pattern=re_pattern,
                string=arxiv_id,
        ):
            raise ValueError(
                f"`arxiv_id` must match the format `2310.17036`; got `{arxiv_id}`.",
            )
        return arxiv_id


## } MODULE
