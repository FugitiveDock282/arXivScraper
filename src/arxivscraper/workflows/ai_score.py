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
## === AI PROVIDER CONFIG
##


def load_provider_config(
    *,
    cli_model: str | None = None,
    cli_base_url: str | None = None,
) -> dict[str, Any]:
    """Load AI provider config from `configs/ai/ai_provider.toml`.

    CLI arguments override any config file values.
    """
    provider_path = directories.ai_configs_dir / config_files.ai_provider
    if not provider_path.is_file():
        raise FileNotFoundError(
            f"no AI config found; create `{provider_path.name}` (see `{config_files.ai_provider_example}`).",
        )
    try:
        with provider_path.open("rb") as file_pointer:
            config = tomllib.load(file_pointer)
    except Exception as error:
        raise ValueError(f"error reading `{provider_path.name}`.") from error
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
            "ai_evidence": [],
            "ai_response": None
        }
    if not article_abstract:
        return {
            "status": "error",
            "error": "Missing article abstract.",
            "ai_rating": None,
            "ai_reason": None,
            "ai_evidence": [],
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
            "ai_evidence": [],
            "ai_response": None
        }
    response_text = (ai_response.choices[0].message.content or "").strip()
    try:
        parsed = parse_llm_json(response_text)
    except Exception as error:
        fallback = _fallback_parse_rating_reason(response_text)
        if fallback is not None:
            return {
                "status": "success",
                "ai_rating": fallback["rating"],
                "ai_reason": fallback["reason"],
                "ai_evidence": [],
                "ai_response": response_text
            }
        return {
            "status": "error",
            "error": f"JSON parsing failed: {error}",
            "ai_rating": None,
            "ai_reason": None,
            "ai_evidence": [],
            "ai_response": response_text
        }
    return {
        "status": "success",
        "ai_rating": parsed["rating"],
        "ai_reason": parsed["reason"],
        "ai_evidence": resolve_ai_evidence(
            abstract=article_abstract,
            rationale=parsed["rationale"],
        ),
        "ai_response": response_text
    }


def parse_llm_json(
    response_text: str,
) -> dict[str, Any]:
    """Parse a scored JSON payload, returning `rating`, `reason`, and raw `rationale`.

    Raises on malformed JSON. `rationale` is optional and defaults to an empty list,
    so a plain `{"rating", "reason"}` response still parses.
    """
    ## strip markdown code fences (e.g. ```json ... ```) if the model wrapped its JSON
    fenced = re.match(r'^\s*```(?:json)?\s*(.*?)\s*```\s*$', response_text, re.DOTALL)
    if fenced:
        response_text = fenced.group(1).strip()
    ## sanitise invalid JSON escape sequences (e.g. LaTeX \gt, \cdot) before parsing
    sanitised = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', response_text)
    response_dict = json.loads(sanitised)
    reason = response_dict["reason"]
    if reason is None:
        reason = ""
    rationale = response_dict.get("rationale") or []
    if not isinstance(rationale, list):
        rationale = []
    return {
        "rating": float(response_dict["rating"]),
        "reason": str(reason),
        "rationale": rationale,
    }


def find_quote_span(
    abstract: str,
    quote: str,
) -> str | None:
    """Return the verbatim substring of `abstract` that `quote` refers to, or `None`.

    The quote must be a contiguous run of the abstract's words; single differences in
    whitespace (or case, as a fallback) are tolerated because models rarely reproduce
    spacing exactly. Returns the exact stored text so highlighting never re-parses.
    """
    quote_tokens = quote.split()
    if not quote_tokens or not abstract:
        return None
    abstract_tokens = [
        match.group()
        for match in re.finditer(r"\S+", abstract)
    ]
    if len(quote_tokens) > len(abstract_tokens):
        return None
    ## positions of each abstract token within the original string
    token_bounds = [
        (match.start(), match.end())
        for match in re.finditer(r"\S+", abstract)
    ]

    def _match_at(
        offset: int,
        *,
        case_sensitive: bool,
    ) -> bool:
        for token_index, quote_token in enumerate(quote_tokens):
            abstract_token = abstract_tokens[offset + token_index]
            if not case_sensitive:
                abstract_token = abstract_token.lower()
                quote_token = quote_token.lower()
            if abstract_token != quote_token:
                return False
        return True

    window = len(quote_tokens)
    for offset in range(len(abstract_tokens) - window + 1):
        if _match_at(offset, case_sensitive=True):
            start = token_bounds[offset][0]
            end = token_bounds[offset + window - 1][1]
            return abstract[start:end]
    for offset in range(len(abstract_tokens) - window + 1):
        if _match_at(offset, case_sensitive=False):
            start = token_bounds[offset][0]
            end = token_bounds[offset + window - 1][1]
            return abstract[start:end]
    return None


def resolve_ai_evidence(
    *,
    abstract: str,
    rationale: list[Any],
) -> list[articles.EvidenceQuote]:
    """Turn raw `rationale` items into `EvidenceQuote`s whose quotes exist verbatim in `abstract`.

    Items with an unrecognised `effect`, a missing/unresolvable quote, or duplicate
    (quote, effect) pairs are dropped.
    """
    evidence: list[articles.EvidenceQuote] = []
    seen: set[tuple[str, str]] = set()
    for item in rationale:
        if not isinstance(item, dict):
            continue
        effect = str(item.get("effect", "")).strip().lower()
        if not articles.is_supported_effect(effect):
            continue
        quote = str(item.get("quote", "")).strip()
        resolved = find_quote_span(abstract, quote)
        if resolved is None:
            continue
        key = (resolved, effect)
        if key in seen:
            continue
        seen.add(key)
        evidence.append(articles.EvidenceQuote(quote=resolved, effect=effect))
    return evidence


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


def check_provider_reachable(
    *,
    ai_client: OpenAI,
    ai_model: str,
) -> None:
    """Send one minimal request to `ai_model` and raise with a clear message if it fails.

    Runs once before the scoring loop so a down/misconfigured provider fails fast with a single
    diagnostic, instead of repeating the same connection/model error once per article.
    """
    response_dict = get_ai_response(
        ai_client=ai_client,
        article_title="Connectivity check.",
        article_abstract="Connectivity check.",
        prompt_rules='Reply with exactly this JSON: {"rating": 0, "reason": "ok"}',
        prompt_criteria='Reply with exactly this JSON: {"rating": 0, "reason": "ok"}',
        ai_model=ai_model,
    )
    if response_dict.get("status") != "success":
        raise RuntimeError(
            f"AI provider check failed: {response_dict.get('error', '<unknown error>')}",
        )


def get_ai_score(
    *,
    article: articles.Article,
    ai_client: OpenAI,
    prompt_rules: str,
    prompt_criteria: str,
    ai_model: str,
) -> bool:
    """Score `article` using the AI model; mutate its `ai_rating`, `ai_reason`, and `ai_evidence` on success."""
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
    article.ai_evidence = list(response_dict.get("ai_evidence") or [])
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
    print("Checking AI provider connectivity...")
    check_provider_reachable(ai_client=ai_client, ai_model=config["model"])
    print("Reading in all articles...")
    articles_list = articles.read_all_markdown_files()
    rescore = bool(score_inputs.get("rescore"))
    if not rescore:
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
