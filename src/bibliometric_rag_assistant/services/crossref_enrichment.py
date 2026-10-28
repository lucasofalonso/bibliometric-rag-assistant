"""Crossref enrichment of a persisted PubMed run.

Citations already processed by Crossref (any status) are skipped, so a new
call resumes an interrupted one.
"""

from datetime import UTC, datetime

import httpx
from sqlalchemy.engine import Engine

from bibliometric_rag_assistant.db_postgres import (
    get_enriched_pmids,
    get_ingestion_run,
    load_citations,
    load_enrichment_gaps,
    save_citation_enrichments,
)
from bibliometric_rag_assistant.ingestion.crossref import (
    check_missing_dois,
    fetch_crossref_work,
    parse_crossref_work,
)

CROSSREF_SOURCE = "crossref"


def enrich_crossref_run(
    run_id: str,
    *,
    engine: Engine,
) -> dict:
    # Reads in a short connection: none is held during the HTTP calls
    with engine.connect() as connection:
        if get_ingestion_run(connection, run_id) is None:
            raise LookupError(f"Run {run_id} does not exist")

        citations = load_citations(connection, run_id)
        enriched_pmids = get_enriched_pmids(connection, run_id, CROSSREF_SOURCE)

    pending = [
        citation
        for citation in citations
        if citation["pmid"] not in enriched_pmids
    ]

    # Split with and without DOI: only citations_with_doi reach Crossref
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

    not_found = []

    # Errors other than 404 stop the execution, but what was already
    # collected is saved first: the affected citation stays pending
    try:
        for citation in report["citations_with_doi"]:
            pmid = citation["pmid"]
            doi = citation["doi"]
            retrieved_at = datetime.now(UTC).isoformat()

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
        save_citation_enrichments(engine, enrichments)

    # Read after saving, so earlier executions are included
    with engine.connect() as connection:
        gaps = load_enrichment_gaps(connection, run_id, CROSSREF_SOURCE)

    return {
        "run_id": run_id,
        "source": CROSSREF_SOURCE,
        "total_citations": len(citations),
        "skipped": len(enriched_pmids),
        "pending": report["total"],
        "with_doi": report["with_doi"],
        "results": {
            status: sum(
                enrichment["status"] == status for enrichment in enrichments
            )
            for status in ["success", "missing_doi", "not_found"]
        },
        "saved": len(enrichments),
        "missing_doi": report["missing"],
        "not_found": not_found,
        "gaps": gaps,
    }
