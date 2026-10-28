"""Persisted PubMed collection: search, fetch, parse and save one run.

The HTTP calls happen first; the run, its snapshots and its citations are
then written in the single transaction of save_ingestion().
"""

from datetime import UTC, datetime
from uuid import uuid4
from xml.etree.ElementTree import ParseError

import httpx
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from bibliometric_rag_assistant.contracts import (
    PubMedCollectionResult,
    PubMedSearchArgs,
)
from bibliometric_rag_assistant.db_postgres import save_ingestion
from bibliometric_rag_assistant.ingestion.pubmed import (
    fetch_pubmed_citations,
    parse_pubmed_xml,
    search_pubmed,
)
from bibliometric_rag_assistant.search_strategy import (
    PUBMED_QUERIES,
    PUBMED_SOURCE,
    PUBMED_VARIANTS,
)


class PubMedSearchError(Exception):
    """ESearch answered, but reported an error instead of a result."""


def resolve_preset(query: str) -> tuple[str | None, str | None]:
    # Only the complete expression, period included, identifies a variant:
    # a reformulated query is an independent search
    for variant_name, preset_query in PUBMED_QUERIES.items():
        if query == preset_query:
            return variant_name, PUBMED_VARIANTS[variant_name]["version"]

    return None, None


def extract_source_warnings(esearch: dict) -> list[str]:
    # ESearch rarely fails outright: missing terms go to errorlist and
    # ignored phrases or repaired syntax to warninglist, with a result
    warnings = []

    for key in ["errorlist", "warninglist"]:
        for kind, messages in (esearch.get(key) or {}).items():
            warnings.extend(f"{kind}: {message}" for message in messages)

    return warnings


def compare_parsed_pmids(pmids: list[str], records: list[dict]) -> list[str]:
    parsed_pmids = {record["pmid"] for record in records}
    retrieved_pmids = set(pmids)

    warnings = []

    not_parsed = [pmid for pmid in pmids if pmid not in parsed_pmids]
    if not_parsed:
        warnings.append(
            f"{len(not_parsed)} PMID(s) retrieved by ESearch were not "
            f"parsed from EFetch: {', '.join(not_parsed)}"
        )

    not_requested = sorted(parsed_pmids - retrieved_pmids)
    if not_requested:
        warnings.append(
            f"{len(not_requested)} parsed record(s) were not in the ESearch "
            f"list: {', '.join(not_requested)}"
        )

    return warnings


def collect_pubmed(
    args: PubMedSearchArgs,
    *,
    engine: Engine,
) -> PubMedCollectionResult:
    now = datetime.now(UTC)
    run_id = str(uuid4())

    # Filled in as the collection advances, so a failure reports how far
    # it got without claiming anything was saved
    progress = {
        "run_id": run_id,
        "query": args.query,
        "requested_count": args.limit,
    }

    try:
        # ESearch: the expression runs exactly as received
        search_result = search_pubmed(args.query, args.limit)
        esearch = search_result.get("esearchresult", {})

        if "ERROR" in esearch or "count" not in esearch:
            raise PubMedSearchError(
                esearch.get("ERROR", "unexpected ESearch response")
            )

        pmids = esearch["idlist"]
        total_results = int(esearch["count"])
        warnings = extract_source_warnings(esearch)

        progress.update(
            total_results=total_results,
            retrieved_count=len(pmids),
            pmids=pmids,
            warnings=warnings,
        )

        # The limit is never reduced: a shortfall is the source's limitation
        expected_count = min(args.limit, total_results)
        if len(pmids) < expected_count:
            warnings.append(
                f"ESearch returned {len(pmids)} PMID(s), fewer than the "
                f"{expected_count} expected for this limit"
            )

        snapshots = [
            {
                "run_id": run_id,
                "endpoint": "esearch",
                "payload_format": "json",
                "payload": search_result,
            }
        ]

        records = []

        # Zero results is a valid run: EFetch is skipped
        if pmids:
            pubmed_xml = fetch_pubmed_citations(pmids)

            snapshots.append(
                {
                    "run_id": run_id,
                    "endpoint": "efetch",
                    "payload_format": "xml",
                    "payload": pubmed_xml,
                }
            )

            records = parse_pubmed_xml(pubmed_xml)
            warnings.extend(compare_parsed_pmids(pmids, records))

        progress["parsed_count"] = len(records)

        query_variant, query_version = resolve_preset(args.query)

        run = {
            "run_id": run_id,
            "source": PUBMED_SOURCE,
            "query_text": args.query,
            "query_variant": query_variant,
            "query_version": query_version,
            "retrieved_at": now.isoformat(),
            "total_results": total_results,
            "total_retrieved": len(pmids),
        }

        save_ingestion(engine, run=run, snapshots=snapshots, records=records)

    except PubMedSearchError as error:
        return PubMedCollectionResult(
            status="error",
            error=f"PubMed reported a search error: {error}. Nothing was saved.",
            **progress,
        )

    except httpx.HTTPStatusError as error:
        return PubMedCollectionResult(
            status="error",
            error=(
                f"PubMed returned HTTP {error.response.status_code} for "
                f"{error.request.url.path}. Nothing was saved."
            ),
            **progress,
        )

    except httpx.RequestError as error:
        return PubMedCollectionResult(
            status="error",
            error=(
                f"Could not reach PubMed ({type(error).__name__}). "
                "Nothing was saved."
            ),
            **progress,
        )

    except ParseError as error:
        return PubMedCollectionResult(
            status="error",
            error=f"Could not parse the EFetch XML ({error}). Nothing was saved.",
            **progress,
        )

    except SQLAlchemyError as error:
        # save_ingestion() rolled the transaction back
        return PubMedCollectionResult(
            status="error",
            error=(
                f"Could not save the run in PostgreSQL "
                f"({type(error).__name__}). Nothing was saved."
            ),
            **progress,
        )

    # Reached only after the commit
    return PubMedCollectionResult(
        status="success",
        saved_count=len(records),
        **progress,
    )
