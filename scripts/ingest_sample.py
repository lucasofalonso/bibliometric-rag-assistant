"""Ingere uma amostra do PubMed e grava no banco SQLite local.

Uso:
    uv run python scripts/ingest_sample.py
"""

import json
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from bibliometric_rag_assistant.config import DB_PATH, RAW_PUBMED_DIR
from bibliometric_rag_assistant.db import (
    connect_database,
    count_rows,
    create_tables,
    save_ingestion,
)
from bibliometric_rag_assistant.ingestion.pubmed import (
    fetch_pubmed_citations,
    parse_pubmed_xml,
    search_pubmed,
)
from bibliometric_rag_assistant.search_strategy import (
    PUBMED_ACTIVE_VARIANT,
    PUBMED_QUERY,
    PUBMED_SAMPLE_SIZE,
    PUBMED_SOURCE,
    PUBMED_VARIANTS,
)


def ingest_sample(
    db_path: str | Path = DB_PATH,
    raw_dir: Path = RAW_PUBMED_DIR,
) -> dict:
    # Configuração
    now = datetime.now(UTC)
    run_id = now.strftime("%Y%m%dT%H%M%SZ")

    # ESearch
    search_result = search_pubmed(PUBMED_QUERY, PUBMED_SAMPLE_SIZE)
    esearch = search_result["esearchresult"]
    pmids = esearch["idlist"]

    # JSON bruto
    search_path = raw_dir / f"{run_id}_esearch.json"
    search_path.write_text(
        json.dumps(search_result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    run = {
        "run_id": run_id,
        "source": PUBMED_SOURCE,
        "query_text": PUBMED_QUERY,
        "query_variant": PUBMED_ACTIVE_VARIANT,
        "query_version": PUBMED_VARIANTS[PUBMED_ACTIVE_VARIANT]["version"],
        "retrieved_at": now.isoformat(),
        "total_results": int(esearch["count"]),
        "total_retrieved": len(pmids),
    }

    snapshots = [
        {
            "run_id": run_id,
            "endpoint": "esearch",
            "payload_format": "json",
            "payload": search_result,
            "file_path": search_path,
        }
    ]

    citations = []

    # Sem PMIDs não há o que buscar: o EFetch com lista vazia retorna erro
    if pmids:
        # EFetch
        pubmed_xml = fetch_pubmed_citations(pmids)

        # XML bruto
        fetch_path = raw_dir / f"{run_id}_efetch.xml"
        fetch_path.write_text(pubmed_xml, encoding="utf-8")

        snapshots.append(
            {
                "run_id": run_id,
                "endpoint": "efetch",
                "payload_format": "xml",
                "payload": pubmed_xml,
                "file_path": fetch_path,
            }
        )

        # Parsing
        citations = parse_pubmed_xml(pubmed_xml)

    # SQLite: cria/abre, grava e fecha
    with closing(connect_database(db_path)) as connection:
        create_tables(connection)
        save_ingestion(connection, run, snapshots, citations)
        totals = count_rows(connection)

    return {
        "run": run,
        "raw_files": [snapshot["file_path"] for snapshot in snapshots],
        "citations_saved": len(citations),
        "db_path": Path(db_path),
        "db_totals": totals,
    }


def print_summary(summary: dict) -> None:
    run = summary["run"]

    print(f"Execução:   {run['run_id']}")
    print(f"Fonte:      {run['source']}")
    print(f"Variante:   {run['query_variant']} (v{run['query_version']})")
    print(f"Resultados: {run['total_results']} encontrados")
    print(f"Amostra:    {run['total_retrieved']} PMIDs recuperados")
    print(f"Citações:   {summary['citations_saved']} gravadas")

    print("Arquivos brutos:")

    for path in summary["raw_files"]:
        print(f"  {path}")

    print(f"Banco: {summary['db_path']}")

    for table, total in summary["db_totals"].items():
        print(f"  {table}: {total} linha(s)")


def main() -> None:
    print_summary(ingest_sample())


if __name__ == "__main__":
    main()
