"""Enrich the citations of a PostgreSQL PubMed run with Crossref metadata.

Usage:
    uv run python scripts/enrich_crossref_sample_postgres.py
    uv run python scripts/enrich_crossref_sample_postgres.py --run-id <run_id>

Without --run-id, the most recent run is used. Citations already processed
are skipped, so running it again resumes an interrupted execution.
"""

import argparse

from bibliometric_rag_assistant.db_postgres import (
    count_rows,
    create_postgres_engine,
    create_tables,
    get_latest_run_id,
)
from bibliometric_rag_assistant.services.crossref_enrichment import (
    enrich_crossref_run,
)


def print_summary(summary: dict, totals: dict[str, int]) -> None:
    results = summary["results"]

    print(f"Run:              {summary['run_id']}")
    print(f"Citations:        {summary['total_citations']}")
    print(f"Already enriched: {summary['skipped']} (skipped)")
    print(f"Pending:          {summary['pending']}")
    print(f"  With DOI:       {summary['with_doi']}")
    print(f"  Without DOI:    {results['missing_doi']}")
    print("Crossref in this execution:")
    print(f"  Found:     {results['success']}")
    print(f"  Not found: {results['not_found']}")
    print(f"  Saved:     {summary['saved']}")

    gaps = summary["gaps"]

    print(
        f"Without Crossref metadata in the run: {len(gaps)} "
        "(to be complemented by OpenAlex)"
    )

    for status in ["missing_doi", "not_found"]:
        status_gaps = [gap for gap in gaps if gap["status"] == status]

        print(f"  {status}: {len(status_gaps)}")

        for gap in status_gaps:
            print(f"    PMID {gap['pmid']} | DOI {gap['doi']} | {gap['title']}")

    print("Database (PostgreSQL):")

    for table, total in totals.items():
        print(f"  {table}: {total} row(s)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--run-id",
        help="Run to enrich (default: the most recent one)",
    )
    args = parser.parse_args()

    engine = create_postgres_engine()

    try:
        create_tables(engine)

        with engine.connect() as connection:
            run_id = args.run_id or get_latest_run_id(connection)

        if run_id is None:
            raise SystemExit(
                "No run in the database: run scripts/ingest_sample_postgres.py first"
            )

        try:
            summary = enrich_crossref_run(run_id, engine=engine)
        except LookupError as error:
            raise SystemExit(str(error)) from None

        with engine.connect() as connection:
            totals = count_rows(connection)
    finally:
        engine.dispose()

    print_summary(summary, totals)


if __name__ == "__main__":
    main()
