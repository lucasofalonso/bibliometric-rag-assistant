"""Collect a PubMed sample and store it in PostgreSQL.

Usage:
    uv run python scripts/ingest_sample_postgres.py
    uv run python scripts/ingest_sample_postgres.py --limit 50
    uv run python scripts/ingest_sample_postgres.py \\
        --query '"temporomandibular joint"[Title/Abstract]' --limit 10

Without --query, the active preset of configs/search_strategy.yaml is used,
period included. Without --limit, the configured sample size is used.
A custom query runs exactly as written: include any date filter in it.
"""

import argparse

from pydantic import ValidationError

from bibliometric_rag_assistant.contracts import (
    PubMedCollectionResult,
    PubMedSearchArgs,
)
from bibliometric_rag_assistant.db_postgres import (
    count_rows,
    create_postgres_engine,
    create_tables,
    get_ingestion_run,
)
from bibliometric_rag_assistant.search_strategy import (
    PUBMED_QUERY,
    PUBMED_SAMPLE_SIZE,
)
from bibliometric_rag_assistant.services.pubmed_collection import collect_pubmed


def print_summary(
    result: PubMedCollectionResult,
    run: dict | None,
    totals: dict[str, int],
) -> None:
    print(f"Status:    {result.status}")
    print(f"Run:       {result.run_id}")
    print(f"Query:     {result.query}")

    if run is not None:
        variant = run["query_variant"] or "none (independent search)"
        version = f" (v{run['query_version']})" if run["query_version"] else ""
        print(f"Preset:    {variant}{version}")

    print(f"Requested: {result.requested_count}")
    print(f"Found:     {result.total_results}")
    print(f"Retrieved: {result.retrieved_count}")
    print(f"Parsed:    {result.parsed_count}")
    print(f"Saved:     {result.saved_count}")

    if result.warnings:
        print("Warnings:")

        for warning in result.warnings:
            print(f"  {warning}")

    if result.error:
        print(f"Error:     {result.error}")

    print("Database (PostgreSQL):")

    for table, total in totals.items():
        print(f"  {table}: {total} row(s)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--query",
        help="PubMed expression to run as is (default: the active preset)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=PUBMED_SAMPLE_SIZE,
        help=f"Maximum number of PMIDs (default: {PUBMED_SAMPLE_SIZE})",
    )
    cli_args = parser.parse_args()

    try:
        args = PubMedSearchArgs(
            query=cli_args.query if cli_args.query is not None else PUBMED_QUERY,
            limit=cli_args.limit,
        )
    except ValidationError as error:
        parser.error(
            "; ".join(
                f"{'.'.join(map(str, item['loc']))}: {item['msg']}"
                for item in error.errors()
            )
        )

    engine = create_postgres_engine()

    try:
        create_tables(engine)
        result = collect_pubmed(args, engine=engine)

        with engine.connect() as connection:
            run = get_ingestion_run(connection, result.run_id)
            totals = count_rows(connection)
    finally:
        engine.dispose()

    print_summary(result, run, totals)

    if result.status != "success":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
