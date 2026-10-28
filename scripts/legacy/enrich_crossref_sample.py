"""Enrich the citations of a PubMed run with Crossref metadata.

Usage:
    uv run python scripts/legacy/enrich_crossref_sample.py
    uv run python scripts/legacy/enrich_crossref_sample.py --run-id 20261016T120000Z

Without --run-id, the most recent run is used. Citations already enriched
are skipped, so running it again resumes an interrupted execution.
"""

import argparse
import json
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import httpx

from bibliometric_rag_assistant.config import DB_PATH, RAW_CROSSREF_DIR
from bibliometric_rag_assistant.ingestion.crossref import (
    check_missing_dois,
    fetch_crossref_work,
    parse_crossref_work,
)
from bibliometric_rag_assistant.legacy.db import (
    connect_database,
    count_rows,
    create_tables,
    get_enriched_pmids,
    get_latest_run_id,
    load_citations,
    load_enrichment_gaps,
    save_citation_enrichments,
)

CROSSREF_SOURCE = "crossref"


def enrich_crossref_sample(
    run_id: str | None = None,
    db_path: str | Path = DB_PATH,
    raw_dir: Path = RAW_CROSSREF_DIR,
) -> dict:
    with closing(connect_database(db_path)) as connection:
        create_tables(connection)

        # Run selection
        run_id = run_id or get_latest_run_id(connection)

        if run_id is None:
            raise RuntimeError(
                "No run in the database: run scripts/legacy/ingest_sample.py first"
            )

        # Citations of the run, minus those already enriched
        citations = load_citations(connection, run_id)

        if not citations:
            raise RuntimeError(f"No citations for run {run_id}")

        enriched_pmids = get_enriched_pmids(connection, run_id, CROSSREF_SOURCE)
        pending = [
            citation
            for citation in citations
            if citation["pmid"] not in enriched_pmids
        ]

        # Split with and without DOI: the fetcher only gets citations_with_doi
        report = check_missing_dois(pending)

        enrichments = [
            {
                "run_id": run_id,
                "pmid": missing["pmid"],
                "source": CROSSREF_SOURCE,
                "doi": None,
                "retrieved_at": datetime.now(UTC).isoformat(),
                "status": "missing_doi",
            }
            for missing in report["missing"]
        ]

        run_raw_dir = raw_dir / run_id
        run_raw_dir.mkdir(parents=True, exist_ok=True)

        raw_files = []
        not_found = []

        # Errors other than 404 stop the execution, but what was already
        # collected is saved first, so the next execution can resume
        try:
            for citation in report["citations_with_doi"]:
                pmid = citation["pmid"]
                doi = citation["doi"]
                retrieved_at = datetime.now(UTC).isoformat()

                # Crossref query
                try:
                    response = fetch_crossref_work(doi)
                except httpx.HTTPStatusError as error:
                    # DOIs from other agencies (DataCite, mEDRA...) return 404
                    if error.response.status_code != 404:
                        raise

                    not_found.append({"pmid": pmid, "doi": doi})
                    enrichments.append(
                        {
                            "run_id": run_id,
                            "pmid": pmid,
                            "source": CROSSREF_SOURCE,
                            "doi": doi,
                            "retrieved_at": retrieved_at,
                            "status": "not_found",
                        }
                    )
                    continue

                # Raw JSON
                raw_path = run_raw_dir / f"{pmid}.json"
                raw_path.write_text(
                    json.dumps(response, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                raw_files.append(raw_path)

                # Parsing
                enrichments.append(
                    {
                        "run_id": run_id,
                        "pmid": pmid,
                        "source": CROSSREF_SOURCE,
                        "doi": doi,
                        "retrieved_at": retrieved_at,
                        "status": "success",
                        "raw": response,
                        "normalized": parse_crossref_work(response["message"]),
                    }
                )
        finally:
            # SQLite: save everything in one transaction
            save_citation_enrichments(connection, enrichments)

        # Read from the database to also include previous executions
        gaps = load_enrichment_gaps(connection, run_id, CROSSREF_SOURCE)
        totals = count_rows(connection)

    return {
        "run_id": run_id,
        "total_citations": len(citations),
        "already_enriched": len(enriched_pmids),
        "pending": report["total"],
        "with_doi": report["with_doi"],
        "missing_doi": report["missing"],
        "success": sum(
            enrichment["status"] == "success" for enrichment in enrichments
        ),
        "not_found": not_found,
        "gaps": gaps,
        "raw_dir": run_raw_dir,
        "raw_files": raw_files,
        "db_path": Path(db_path),
        "db_totals": totals,
    }


def print_summary(summary: dict) -> None:
    print(f"Run:              {summary['run_id']}")
    print(f"Citations:        {summary['total_citations']}")
    print(f"Already enriched: {summary['already_enriched']} (skipped)")
    print(f"Pending:          {summary['pending']}")
    print(f"  With DOI:       {summary['with_doi']}")
    print(f"  Without DOI:    {len(summary['missing_doi'])}")
    print("Crossref in this execution:")
    print(f"  Found:     {summary['success']}")
    print(f"  Not found: {len(summary['not_found'])}")
    print(f"Raw files: {len(summary['raw_files'])} in {summary['raw_dir']}")

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

    print(f"Database: {summary['db_path']}")

    for table, total in summary["db_totals"].items():
        print(f"  {table}: {total} row(s)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--run-id",
        help="Run to enrich (default: the most recent one)",
    )
    args = parser.parse_args()

    print_summary(enrich_crossref_sample(run_id=args.run_id))


if __name__ == "__main__":
    main()
