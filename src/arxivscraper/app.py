## { MODULE

##
## === DEPENDENCIES
##

## stdlib
import datetime
import time

## local
from arxivscraper.support import script_cli
from arxivscraper.workflows import ai_score, browse_papers, download_pdfs, fetch_paper, retag, search_arxiv, sync_sheets

##
## === MAIN
##


def main() -> None:
    time_start = time.time()
    print(
        "Program started at {}".format(
            datetime.datetime.now().strftime("%H:%M:%S"),
        ),
    )
    user_inputs = script_cli.CLIParser(
        include_main=True,
        include_search=True,
        include_fetch=True,
        include_score=True,
    )
    program_flags = user_inputs.get_program_inputs()
    if program_flags["search"]:
        search_arxiv.main()
        if program_flags["score"]:
            ai_score.main()
    elif program_flags["score"]:
        ai_score.main()
    elif program_flags["fetch"]:
        fetch_paper.main()
    elif program_flags["download"]:
        download_pdfs.main()
    elif program_flags["browse"]:
        browse_papers.main()
    elif program_flags["retag"]:
        retag.main()
    elif program_flags["sync"]:
        sync_sheets.main()
    time_elapsed = time.time() - time_start
    print(f"Elapsed time: {time_elapsed:.2f} seconds.")


## } MODULE
