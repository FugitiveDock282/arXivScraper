## { SCRIPT

##
## === DEPENDENCIES
##

## stdlib
import json
import re
import sys
import time
import tomllib
from typing import Any

## third-party
from openai import OpenAI

## local
from arxivscraper.config_paths import directories, files as config_files
from arxivscraper.support import articles, file_io, script_cli

##
## === CONSTANTS
##

_DEFAULT_MODEL = "gpt-4o-mini"

##
## === AI PROVIDER CONFIG
##


def load_provider_config(
    *,
    cli_model: str | None = None,
    cli_base_url: str | None = None,
) -> dict[str, Any]:
    """Load AI provider config from `configs/ai/ai_provider.toml`, falling back to the legacy `api_key.txt`.

    CLI arguments override any config file values.
    """
    provider_path = directories.ai_configs_dir / config_files.ai_provider
    if provider_path.is_file():
        try:
            with provider_path.open("rb") as file_pointer:
                config = tomllib.load(file_pointer)
        except Exception as error:
            raise ValueError(f"error reading `{provider_path.name}`.") from error
    else:
        key_path = directories.ai_configs_dir / config_files.ai_api_key
        if not key_path.is_file():
            raise FileNotFoundError(
                f"no AI config found; create `{provider_path.name}` "
                f"(see `{config_files.ai_provider_example}`) "
                f"or the legacy `{key_path.name}`.",
            )
        api_key = None
        for line in key_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip().strip("'").strip('"')
            if stripped:
                api_key = stripped
                break
        if not api_key:
            raise ValueError(f"`{config_files.ai_api_key}` is empty.")
        config = {"api_key": api_key, "base_url": None, "model": _DEFAULT_MODEL}
    if cli_model:
        config["model"] = cli_model
    if cli_base_url:
        config["base_url"] = cli_base_url
    if not config.get("api_key"):
        raise ValueError(
            "no `api_key` in provider config; "
            "local servers (Ollama, LM Studio) use a placeholder like `local`.",
        )
    if not config.get("model"):
        raise ValueError("no `model` specified in provider config.")
    return config


##
## === AI CLIENT
##


def create_ai_client(
    api_key: str,
    *,
    base_url: str | None = None,
) -> OpenAI:
    """Create and return an `OpenAI` client configured with `api_key` and optional `base_url`."""
    client_kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    return OpenAI(**client_kwargs)


##
## === AI SCORING
##


def get_ai_response(
    *,
    ai_client: OpenAI,
    article_title: str,
    article_abstract: str,
    prompt_rules: str,
    prompt_criteria: str,
    ai_model: str,
) -> dict[str, Any]:
    """Send `article_title` and `article_abstract` to the AI model and return the parsed response dict."""
    if not article_title:
        return {
            "status": "error",
            "error": "Missing article title.",
            "ai_rating": None,
            "ai_reason": None,
            "ai_response": None
        }
    if not article_abstract:
        return {
            "status": "error",
            "error": "Missing article abstract.",
            "ai_rating": None,
            "ai_reason": None,
            "ai_response": None
        }
    prompt_input = f"{prompt_criteria}\n\nTITLE: {article_title}\n\nABSTRACT: {article_abstract}"
    try:
        ai_response = ai_client.chat.completions.create(
            model=ai_model,
            messages=[
                {
                    "role": "system",
                    "content": prompt_rules
                },
                {
                    "role": "user",
                    "content": prompt_input
                },
            ],
            temperature=0.0,
        )
    except Exception as error:
        return {
            "status": "error",
            "error": f"API call failed: {error}",
            "ai_rating": None,
            "ai_reason": None,
            "ai_response": None
        }
    response_text = ""
    try:
        response_text = (ai_response.choices[0].message.content or "").strip()
        ## sanitise invalid JSON escape sequences (e.g. LaTeX \gt, \cdot) before parsing
        sanitised = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', response_text)
        response_dict = json.loads(sanitised)
        ai_rating = float(response_dict["rating"])
        ai_reason = response_dict["reason"]
        return {
            "status": "success",
            "ai_rating": ai_rating,
            "ai_reason": ai_reason,
            "ai_response": response_text
        }
    except Exception as error:
        fallback = _fallback_parse_rating_reason(response_text)
        if fallback is not None:
            return {
                "status": "success",
                "ai_rating": fallback["rating"],
                "ai_reason": fallback["reason"],
                "ai_response": response_text
            }
        return {
            "status": "error",
            "error": f"JSON parsing failed: {error}",
            "ai_rating": None,
            "ai_reason": None,
            "ai_response": response_text
        }


def _fallback_parse_rating_reason(
    response_text: str,
) -> dict[str, Any] | None:
    """Recover `rating`/`reason` via regex when the model emits near-JSON with an unclosed or malformed string."""
    rating_match = re.search(r'"rating"\s*:\s*([0-9]+(?:\.[0-9]+)?)', response_text)
    reason_match = re.search(r'"reason"\s*:\s*"(.*)"\s*\}?\s*$', response_text, re.DOTALL)
    if not rating_match or not reason_match:
        return None
    reason_text = reason_match.group(1).replace('\\"', '"').replace("\n", " ").strip()
    return {
        "rating": float(rating_match.group(1)),
        "reason": reason_text,
    }


def get_ai_score(
    *,
    article: articles.Article,
    ai_client: OpenAI,
    prompt_rules: str,
    prompt_criteria: str,
    ai_model: str,
) -> bool:
    """Score `article` using the AI model; mutate its `ai_rating` and `ai_reason` on success."""
    time_start = time.time()
    response_dict = get_ai_response(
        ai_client=ai_client,
        article_title=article.title,
        article_abstract=article.abstract,
        prompt_rules=prompt_rules,
        prompt_criteria=prompt_criteria,
        ai_model=ai_model,
    )
    time_elapsed = time.time() - time_start
    if response_dict.get("status") != "success":
        print("Error:", response_dict.get("error", "<unknown error>"))
        ai_response = response_dict.get("ai_response")
        if ai_response:
            print("Raw LLM response:", ai_response)
        return False
    print("arXiv-id:", article.arxiv_id)
    print("Title:", article.title.strip())
    print("Rating:", response_dict.get("ai_rating"))
    print(f"Elapsed time: {time_elapsed:.2f} seconds.")
    article.ai_rating = response_dict.get("ai_rating")
    article.ai_reason = response_dict.get("ai_reason")
    return True


##
## === PROGRAM MAIN
##


def main() -> None:
    user_inputs = script_cli.CLIParser(include_score=True)
    score_inputs = user_inputs.get_score_inputs()
    config = load_provider_config(
        cli_model=score_inputs.get("model"),
        cli_base_url=score_inputs.get("base_url"),
    )
    ai_client = create_ai_client(
        api_key=config["api_key"],
        base_url=config.get("base_url"),
    )
    print(f"Model: {config['model']}")
    if config.get("base_url"):
        print(f"Base URL: {config['base_url']}")
    print("Reading in all articles...")
    articles_list = articles.read_all_markdown_files()
    articles_list = [article for article in articles_list if article.ai_rating is None]
    num_articles = len(articles_list)
    print(f"Preparing to score {num_articles} articles.")
    prompt_rules = file_io.read_text_file(directories.ai_configs_dir / config_files.ai_rules)
    prompt_criteria = file_io.read_text_file(directories.ai_configs_dir / config_files.ai_criteria)
    for article_index, article in enumerate(articles_list):
        print(f"({article_index+1}/{num_articles})")
        is_scored = get_ai_score(
            article=article,
            ai_client=ai_client,
            prompt_rules=prompt_rules,
            prompt_criteria=prompt_criteria,
            ai_model=config["model"],
        )
        if is_scored:
            articles.save_article(
                article,
                force=True,
            )


##
## === ENTRY POINT
##

if __name__ == "__main__":
    main()
    sys.exit(0)

## } SCRIPT
