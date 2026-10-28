import argparse
import json
from collections.abc import Callable
from typing import Annotated

import httpx
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel

from bibliometric_rag_assistant.contracts import PubMedSearchArgs
from bibliometric_rag_assistant.ingestion.crossref import (
    fetch_crossref_work,
    parse_crossref_work,
)
from bibliometric_rag_assistant.ingestion.pubmed import (
    fetch_pubmed_citations,
    parse_pubmed_xml,
    search_pubmed,
)
from bibliometric_rag_assistant.search_strategy import (
    PUBMED_PERIOD,
    PUBMED_QUERY,
    PUBMED_SAMPLE_SIZE,
)

load_dotenv()

MODEL = "gpt-5.4-mini"
MAX_TOOL_CALLS = 4

openai_client = OpenAI()


# Tool contracts: PubMedSearchArgs is shared from contracts.py

Pmid = Annotated[str, Field(pattern=r"^[0-9]+$")]


class PubMedCitationsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    pmids: list[Pmid] = Field(
        min_length=1,
        description="PMIDs provided by the user or returned by the search.",
    )


class CrossrefWorkArgs(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
    )

    doi: str = Field(
        min_length=1,
        description=(
            "DOI provided by the user or obtained from the metadata. "
            "Provide only the DOI, without the https://doi.org/ prefix."
        ),
    )


# Tools: produce the observations returned to the agent

def run_pubmed_search(query: str, limit: int) -> dict:
    raw_results = search_pubmed(query=query, limit=limit)
    esearch = raw_results["esearchresult"]

    return {
        "status": "success",
        "source": "pubmed",
        "query": query,
        "requested_count": limit,
        "total_results": int(esearch["count"]),
        "returned_count": len(esearch["idlist"]),
        "pmids": esearch["idlist"],
    }


def get_pubmed_citations(pmids: list[str]) -> dict:
    xml = fetch_pubmed_citations(pmids)
    citations = parse_pubmed_xml(xml)

    returned_pmids = {record["pmid"] for record in citations}

    return {
        "status": "success",
        "source": "pubmed",
        "requested_pmids": pmids,
        "returned_count": len(citations),
        "missing_pmids": [
            pmid for pmid in pmids
            if pmid not in returned_pmids
        ],
        "citations": citations,
    }


def get_crossref_work(doi: str) -> dict:
    try:
        payload = fetch_crossref_work(doi)

    except httpx.HTTPStatusError as error:
        if error.response.status_code != 404:
            raise

        return {
            "status": "not_found",
            "source": "crossref",
            "doi": doi,
        }

    return {
        "status": "success",
        "source": "crossref",
        "work": parse_crossref_work(payload["message"]),
    }


TOOL_REGISTRY = {
    "search_pubmed": {
        "args_model": PubMedSearchArgs,
        "handler": run_pubmed_search,
        "description": (
            "Search PubMed and return the total number of matching records "
            "and a limited list of PMIDs. "
            "Use this to discover records; obtain publication details "
            "with a separate metadata tool."
        ),
    },
    "get_pubmed_citations": {
        "args_model": PubMedCitationsArgs,
        "handler": get_pubmed_citations,
        "description": (
            "Look up the PubMed metadata of known PMIDs. "
            "Returns title, DOI, journal and publication year. "
            "Use it to get details of the records found by the search."
        ),
    },
    "get_crossref_work": {
        "args_model": CrossrefWorkArgs,
        "handler": get_crossref_work,
        "description": (
            "Look up a DOI in Crossref. Returns metadata and the reference "
            "and citation counts available from this source. "
            "Requires a DOI provided by the user or obtained from another tool."
        ),
    },
}

# Readable names shown by the interfaces while a tool runs
TOOL_LABELS = {
    "search_pubmed": "Searching PubMed",
    "get_pubmed_citations": "Fetching PubMed metadata",
    "get_crossref_work": "Querying Crossref",
}

TOOLS = [
    {
        "type": "function",
        "name": name,
        "description": spec["description"],
        "parameters": spec["args_model"].model_json_schema(),
        "strict": True,
    }
    for name, spec in TOOL_REGISTRY.items()
]


# Executor: validates the arguments and runs the tool

def make_call(call):
    if call.name not in TOOL_REGISTRY:
        raise ValueError(f"Unknown tool: {call.name}")

    spec = TOOL_REGISTRY[call.name]

    try:
        args = spec["args_model"].model_validate_json(call.arguments)

    except ValidationError as error:
        result = {
            "status": "invalid_arguments",
            "errors": [
                {
                    "field": list(item["loc"]),
                    "message": item["msg"],
                }
                for item in error.errors()
            ],
        }

    else:
        try:
            result = spec["handler"](**args.model_dump())

        except httpx.HTTPStatusError as error:
            result = {
                "status": "external_error",
                "tool": call.name,
                "http_status": error.response.status_code,
                "message": "The service returned an HTTP error.",
            }

        except httpx.RequestError:
            result = {
                "status": "external_error",
                "tool": call.name,
                "message": "Could not complete the connection to the service.",
            }

    return {
        "type": "function_call_output",
        "call_id": call.call_id,
        "output": json.dumps(result, ensure_ascii=False),
    }


# Agentic loop

instructions = f"""
You assist with bibliographic queries on PubMed.

Study preset:
The project studies infection in temporomandibular joint (TMJ)
replacement. Its preset query, already restricted to the study period
({PUBMED_PERIOD["start"]} to {PUBMED_PERIOD["end"]}), is:
{PUBMED_QUERY}

- Use the preset exactly as written when the user refers to the
  "current query", the project's query or this TMJ study.
- If the user asks to change the preset (terms, fields or period), the
  result is a new query of your own: say it is no longer the study preset.

Queries for other subjects:
- Build your own query. Never reuse the preset or its period.
- Split the question into concept groups. Join synonyms, spelling
  variants and acronyms inside a group with OR, wrap each group in
  parentheses and join the groups with AND. Use NOT only when the user
  asks to exclude something.
- Tag free-text terms with [Title/Abstract]. Use quotes for exact
  phrases and * for truncation (prosthe*).
- Use [MeSH Terms] when the concept has a well-established MeSH heading,
  combined with free-text terms in the same group: recent records may not
  be indexed with MeSH yet. Do not invent MeSH headings; when unsure,
  rely on free text.
- Add a date filter only when the user asks for a period, writing it in
  the query itself, for example:
  ("2015/01/01"[Date - Publication] : "2020/12/31"[Date - Publication])
- Without a requested period, the query has no date filter.
- The query you send is executed exactly as written: send the complete
  expression, and show it to the user in the answer.

Guidelines:
- Use as limit the quantity explicitly requested by the user.
- When no quantity is given, use {PUBMED_SAMPLE_SIZE}.
- Respect the technical limits described in the tool schema.
- Distinguish requested quantity, total found and returned quantity.
- If the requested quantity exceeds the total found, explain that
  the search found fewer records than requested.
- Base numbers and PMIDs exclusively on the tool results.
- When you receive status invalid_arguments, examine the errors and fix
  the arguments before trying again, respecting the call budget.
- To get details of a PMID, use get_pubmed_citations.
- To query Crossref, use a DOI provided by the user or returned
  by a tool. Never invent a DOI.
- When the DOI is missing or Crossref returns not_found,
  explain this absence.
- Distinguish reference counts from citation counts and
  identify Crossref as the source of these counts.
- If there is an external_error, explain that the query was not completed.
- Reply in the same language as the user.
"""


def run_agent(
    question: str,
    history: list | None = None,
    verbose: bool = True,
    on_tool_call: Callable[[str], None] | None = None,
) -> dict:
    # Without history, the conversation starts from scratch. With history,
    # the question and the whole turn trajectory are appended to the same
    # list, which can be reused for the next question
    if history is None:
        history = [{"role": "developer", "content": instructions}]

    history.append({"role": "user", "content": question})

    call_log = []
    stop_reason = None
    tool_call_count = 0
    final_answer = None
    it = 0

    while True:
        if verbose:
            print(f'iteration #{it}...')
        has_function_calls = False

        response = openai_client.responses.create(
            model=MODEL,
            input=history,
            tools=TOOLS,
            parallel_tool_calls=False,
        )
        history.extend(response.output)

        for item in response.output:
            if item.type == 'function_call':
                if tool_call_count >= MAX_TOOL_CALLS:
                    stop_reason = 'max_tool_calls'

                    # Every function_call in the history needs an output,
                    # otherwise the API rejects the next question
                    history.append({
                        "type": "function_call_output",
                        "call_id": item.call_id,
                        "output": json.dumps(
                            {
                                "status": "not_executed",
                                "message": "Tool call budget exhausted.",
                            },
                            ensure_ascii=False,
                        ),
                    })
                    break

                if verbose:
                    print('function_call:', item.name, item.arguments)
                if on_tool_call:
                    on_tool_call(item.name)
                call_output = make_call(item)
                tool_call_count += 1

                call_log.append({
                    'tool': item.name,
                    'arguments': json.loads(item.arguments),
                    'result': json.loads(call_output["output"]),
                })

                history.append(call_output)
                has_function_calls = True

            elif item.type == 'message':
                final_answer = item.content[0].text
                if verbose:
                    print('ASSISTANT:')
                    print(final_answer)

        if stop_reason == 'max_tool_calls':
            if verbose:
                print(f'Stopping: limit of {MAX_TOOL_CALLS} tool calls reached.')
            break

        it += 1
        if not has_function_calls:
            stop_reason = 'end_turn'
            break

    return {
        'answer': final_answer,
        'call_log': call_log,
        'stop_reason': stop_reason,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Terminal chat with the PubMed/Crossref typed-tools agent.",
    )
    parser.add_argument(
        "question",
        nargs="?",
        help="First question for the agent (optional)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show the iterations and tool calls",
    )
    args = parser.parse_args()

    # The same history carries over across all questions of the conversation
    history = [{"role": "developer", "content": instructions}]
    question = args.question

    console = Console()
    console.print(
        Panel.fit(
            "[bold]PubMed/Crossref Agent[/]\n"
            "[dim]Type 'exit' or press Ctrl+D to quit.[/]",
            border_style="cyan",
        )
    )

    try:
        while True:
            # PubMed queries have brackets ([MeSH Terms]) that rich would
            # read as markup: the user's text is always escaped
            if question is None:
                question = console.input("\n[bold cyan]You ›[/] ").strip()
            else:
                console.print(f"\n[bold cyan]You ›[/] {escape(question)}")

            if question.lower() in {"exit", "quit"}:
                break

            if question:
                with console.status("Thinking...", spinner="dots") as status:
                    result = run_agent(
                        question,
                        history=history,
                        verbose=args.verbose,
                        on_tool_call=lambda name: status.update(
                            f"{TOOL_LABELS.get(name, name)}..."
                        ),
                    )

                answer = result["answer"] or (
                    f"_No final answer ({result['stop_reason']})._"
                )
                console.print()
                console.print(
                    Panel(
                        Markdown(answer),
                        title="Assistant",
                        title_align="left",
                        border_style="green",
                        padding=(1, 2),
                    )
                )

            question = None

    except (EOFError, KeyboardInterrupt):
        console.print()


if __name__ == "__main__":
    main()
