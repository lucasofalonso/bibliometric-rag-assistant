import json
import sqlite3
from contextlib import closing
from pathlib import Path

from bibliometric_rag_assistant.config import DB_PATH

TABLES = (
    "ingestion_runs",
    "raw_snapshots",
    "citations",
    "citation_enrichments",
)


def connect_database(db_path: str | Path = DB_PATH) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON" )

    return connection


def create_tables(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS ingestion_runs (
            run_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            query_text TEXT NOT NULL,
            query_variant TEXT NOT NULL,
            query_version TEXT NOT NULL,
            retrieved_at TEXT NOT NULL,
            total_results INTEGER NOT NULL,
            total_retrieved INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS raw_snapshots (
            snapshot_id INTEGER PRIMARY KEY,
            run_id TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            payload_format TEXT NOT NULL,
            payload TEXT NOT NULL,
            file_path TEXT NOT NULL,

            UNIQUE (run_id, endpoint),

            FOREIGN KEY (run_id)
                REFERENCES ingestion_runs (run_id)
        );

        CREATE TABLE IF NOT EXISTS citations (
            run_id TEXT NOT NULL,
            pmid TEXT NOT NULL,
            doi TEXT,
            title TEXT,
            abstract TEXT,
            journal TEXT,
            publication_year INTEGER,
            language TEXT,
            authors_json TEXT NOT NULL,
            affiliations_json TEXT NOT NULL,

            PRIMARY KEY (run_id, pmid),

            FOREIGN KEY (run_id)
                REFERENCES ingestion_runs (run_id)
        );

        CREATE TABLE IF NOT EXISTS citation_enrichments (
            run_id TEXT NOT NULL,
            pmid TEXT NOT NULL,
            source TEXT NOT NULL,
            doi TEXT,
            retrieved_at TEXT NOT NULL,
            status TEXT NOT NULL,
            raw_json TEXT,
            normalized_json TEXT,

            PRIMARY KEY (run_id, pmid, source),

            FOREIGN KEY (run_id, pmid)
                REFERENCES citations (run_id, pmid),

            CHECK (
                status IN (
                    'success',
                    'missing_doi',
                    'not_found'
                )
            )
        );
        """
    )

    connection.commit()


def insert_ingestion_run(
        connection: sqlite3.Connection, 
        run: dict
) -> None:
    connection.execute(
        """
        INSERT INTO ingestion_runs (
            run_id,
            source,
            query_text,
            query_variant,
            query_version,
            retrieved_at,
            total_results,
            total_retrieved
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run["run_id"],
            run["source"],
            run["query_text"],
            run["query_variant"],
            run["query_version"],
            run["retrieved_at"],
            run["total_results"],
            run["total_retrieved"],
        ),
    )


def insert_raw_snapshot(
    connection: sqlite3.Connection,
    snapshot: dict,
) -> None:
    payload = snapshot["payload"]

    if not isinstance(payload, str):
        payload = json.dumps(
            payload,
            ensure_ascii=False,
        )

    connection.execute(
        """
        INSERT INTO raw_snapshots (
            run_id,
            endpoint,
            payload_format,
            payload,
            file_path
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            snapshot["run_id"],
            snapshot["endpoint"],
            snapshot["payload_format"],
            payload,
            str(snapshot["file_path"]),
        ),
    )


def insert_citations(
    connection: sqlite3.Connection,
    run_id: str,
    citations: list[dict],
) -> None:
    rows = [
        (
            run_id,
            citation["pmid"],
            citation.get("doi"),
            citation.get("title"),
            citation.get("abstract"),
            citation.get("journal"),
            citation.get("publication_year"),
            citation.get("language"),
            json.dumps(
                citation.get("authors", []),
                ensure_ascii=False,
            ),
            json.dumps(
                citation.get("affiliations", []),
                ensure_ascii=False,
            ),
        )
        for citation in citations
    ]

    connection.executemany(
        """
        INSERT INTO citations (
            run_id,
            pmid,
            doi,
            title,
            abstract,
            journal,
            publication_year,
            language,
            authors_json,
            affiliations_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def dumps_or_none(value) -> str | None:
    # missing_doi and not_found have no response or record: store NULL
    if value is None:
        return None

    return json.dumps(value, ensure_ascii=False)


def insert_citation_enrichments(
    connection: sqlite3.Connection,
    enrichments: list[dict],
) -> None:
    rows = [
        (
            enrichment["run_id"],
            enrichment["pmid"],
            enrichment["source"],
            enrichment.get("doi"),
            enrichment["retrieved_at"],
            enrichment["status"],
            dumps_or_none(enrichment.get("raw")),
            dumps_or_none(enrichment.get("normalized")),
        )
        for enrichment in enrichments
    ]

    connection.executemany(
        """
        INSERT INTO citation_enrichments (
            run_id,
            pmid,
            source,
            doi,
            retrieved_at,
            status,
            raw_json,
            normalized_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def save_ingestion(
    connection: sqlite3.Connection,
    run: dict,
    snapshots: list[dict],
    citations: list[dict],
) -> None:
    try:
        insert_ingestion_run(connection, run)

        for snapshot in snapshots:
            insert_raw_snapshot(connection, snapshot)

        insert_citations(connection, run["run_id"], citations)

        connection.commit()
    except Exception:
        connection.rollback()
        raise


def save_citation_enrichments(
    connection: sqlite3.Connection,
    enrichments: list[dict],
) -> None:
    try:
        insert_citation_enrichments(connection, enrichments)

        connection.commit()
    except Exception:
        connection.rollback()
        raise


def get_latest_run_id(connection: sqlite3.Connection) -> str | None:
    row = connection.execute(
        """
        SELECT run_id
        FROM ingestion_runs
        ORDER BY retrieved_at DESC
        LIMIT 1
        """
    ).fetchone()

    return row[0] if row else None


def load_citations(
    connection: sqlite3.Connection,
    run_id: str,
) -> list[dict]:
    cursor = connection.execute(
        """
        SELECT run_id, pmid, doi, title
        FROM citations
        WHERE run_id = ?
        ORDER BY pmid
        """,
        (run_id,),
    )
    columns = [description[0] for description in cursor.description]

    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def get_enriched_pmids(
    connection: sqlite3.Connection,
    run_id: str,
    source: str,
) -> set[str]:
    rows = connection.execute(
        """
        SELECT pmid
        FROM citation_enrichments
        WHERE run_id = ? AND source = ?
        """,
        (run_id, source),
    ).fetchall()

    return {row[0] for row in rows}


def load_enrichment_gaps(
    connection: sqlite3.Connection,
    run_id: str,
    source: str,
) -> list[dict]:
    # Citations the source could not enrich (no DOI or 404),
    # candidates to be complemented by another source
    cursor = connection.execute(
        """
        SELECT
            enrichments.status,
            citations.pmid,
            citations.doi,
            citations.title
        FROM citation_enrichments AS enrichments
        JOIN citations
            ON citations.run_id = enrichments.run_id
            AND citations.pmid = enrichments.pmid
        WHERE enrichments.run_id = ?
        AND enrichments.source = ?
        AND enrichments.status <> 'success'
        ORDER BY enrichments.status, citations.pmid
        """,
        (run_id, source),
    )
    columns = [description[0] for description in cursor.description]

    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def count_rows(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in TABLES
    }


def main() -> None:
    with closing(connect_database()) as connection:
        create_tables(connection)
        counts = count_rows(connection)

    print(f"Database: {DB_PATH}")

    for table, total in counts.items():
        print(f"  {table}: {total} row(s)")


if __name__ == "__main__":
    main()
