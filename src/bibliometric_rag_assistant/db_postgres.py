import json

from sqlalchemy import (
    URL,
    CheckConstraint,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    select,
)
from sqlalchemy.engine import Connection, Engine

from bibliometric_rag_assistant.settings import get_postgres_settings


def create_postgres_engine() -> Engine:
    database_url = URL.create(
        "postgresql+psycopg",
        **get_postgres_settings(),
    )

    return create_engine(database_url)

# Table definitions
metadata = MetaData()

ingestion_runs = Table(
    "ingestion_runs",
    metadata,
    Column("run_id", Text, primary_key=True),
    Column("source", Text, nullable=False),
    Column("query_text", Text, nullable=False),
    # NULL for independent searches: only an exact preset match is identified
    Column("query_variant", Text, nullable=True),
    Column("query_version", Text, nullable=True),
    Column("retrieved_at", Text, nullable=False),
    Column("total_results", Integer, nullable=False),
    Column("total_retrieved", Integer, nullable=False),
)

raw_snapshots = Table(
    "raw_snapshots",
    metadata,
    Column("snapshot_id", Integer, Identity(), primary_key=True),
    Column(
        "run_id",
        Text,
        ForeignKey("ingestion_runs.run_id"),
        nullable=False,
    ),
    Column("endpoint", Text, nullable=False),
    Column("payload_format", Text, nullable=False),
    Column("payload", Text, nullable=False),
    # Payload lives in the database: the file path is optional
    Column("file_path", Text, nullable=True),
    UniqueConstraint(
        "run_id",
        "endpoint",
        name="uq_raw_snapshots_run_endpoint",
    ),
)

citations = Table(
    "citations",
    metadata,
    Column(
        "run_id",
        Text,
        ForeignKey("ingestion_runs.run_id"),
        primary_key=True,
    ),
    Column("pmid", Text, primary_key=True),
    Column("doi", Text),
    Column("title", Text),
    Column("abstract", Text),
    Column("journal", Text),
    Column("publication_year", Integer),
    Column("language", Text),
    Column("authors_json", Text, nullable=False),
    Column("affiliations_json", Text, nullable=False),
)

citation_enrichments = Table(
    "citation_enrichments",
    metadata,
    Column("run_id", Text, primary_key=True),
    Column("pmid", Text, primary_key=True),
    Column("source", Text, primary_key=True),
    Column("doi", Text),
    Column("retrieved_at", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("raw_json", Text),
    Column("normalized_json", Text),
    ForeignKeyConstraint(
        ["run_id", "pmid"],
        ["citations.run_id", "citations.pmid"],
        name="fk_citation_enrichments_citation",
    ),
    CheckConstraint(
        "status IN ('success', 'missing_doi', 'not_found')",
        name="ck_citation_enrichments_status",
    ),
)


def create_tables(engine: Engine) -> None:
    metadata.create_all(engine)


def insert_ingestion_run(connection: Connection, run: dict) -> None:
    connection.execute(ingestion_runs.insert(), run)


def insert_raw_snapshot(
    connection: Connection,
    snapshot: dict,
) -> None:
    payload = snapshot["payload"]

    if not isinstance(payload, str):
        payload = json.dumps(payload, ensure_ascii=False)

    file_path = snapshot.get("file_path")

    connection.execute(
        raw_snapshots.insert(),
        {
            "run_id": snapshot["run_id"],
            "endpoint": snapshot["endpoint"],
            "payload_format": snapshot["payload_format"],
            "payload": payload,
            "file_path": str(file_path) if file_path is not None else None,
        },
    )


def insert_citations(
    connection: Connection,
    run_id: str,
    records: list[dict],
) -> None:
    rows = [
        {
            "run_id": run_id,
            "pmid": record["pmid"],
            "doi": record.get("doi"),
            "title": record.get("title"),
            "abstract": record.get("abstract"),
            "journal": record.get("journal"),
            "publication_year": record.get("publication_year"),
            "language": record.get("language"),
            "authors_json": json.dumps(
                record.get("authors", []),
                ensure_ascii=False,
            ),
            "affiliations_json": json.dumps(
                record.get("affiliations", []),
                ensure_ascii=False,
            ),
        }
        for record in records
    ]

    # An empty list would run a single INSERT without values: skip it
    if rows:
        connection.execute(citations.insert(), rows)


def dumps_or_none(value) -> str | None:
    # missing_doi and not_found have no response or record: store NULL
    if value is None:
        return None

    return json.dumps(value, ensure_ascii=False)


def insert_citation_enrichments(
    connection: Connection,
    enrichments: list[dict],
) -> None:
    rows = [
        {
            "run_id": enrichment["run_id"],
            "pmid": enrichment["pmid"],
            "source": enrichment["source"],
            "doi": enrichment.get("doi"),
            "retrieved_at": enrichment["retrieved_at"],
            "status": enrichment["status"],
            "raw_json": dumps_or_none(enrichment.get("raw")),
            "normalized_json": dumps_or_none(
                enrichment.get("normalized")
            ),
        }
        for enrichment in enrichments
    ]

    if rows:
        connection.execute(citation_enrichments.insert(), rows)


def save_ingestion(
    engine: Engine,
    run: dict,
    snapshots: list[dict],
    records: list[dict],
) -> None:
    # engine.begin() commits on success and rolls back on any exception
    with engine.begin() as connection:
        insert_ingestion_run(connection, run)

        for snapshot in snapshots:
            insert_raw_snapshot(connection, snapshot)

        insert_citations(connection, run["run_id"], records)


def save_citation_enrichments(
    engine: Engine,
    enrichments: list[dict],
) -> None:
    with engine.begin() as connection:
        insert_citation_enrichments(connection, enrichments)


def get_latest_run_id(connection: Connection) -> str | None:
    return connection.execute(
        select(ingestion_runs.c.run_id)
        .order_by(ingestion_runs.c.retrieved_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def get_ingestion_run(
    connection: Connection,
    run_id: str,
) -> dict | None:
    row = connection.execute(
        select(ingestion_runs).where(ingestion_runs.c.run_id == run_id)
    ).mappings().one_or_none()

    return dict(row) if row is not None else None


def load_citations(
    connection: Connection,
    run_id: str,
) -> list[dict]:
    rows = connection.execute(
        select(citations)
        .where(citations.c.run_id == run_id)
        .order_by(citations.c.pmid)
    ).mappings().all()

    records = []

    for row in rows:
        record = dict(row)
        record["authors"] = json.loads(record.pop("authors_json"))
        record["affiliations"] = json.loads(record.pop("affiliations_json"))
        records.append(record)

    return records


def get_enriched_pmids(
    connection: Connection,
    run_id: str,
    source: str,
) -> set[str]:
    # Every status counts as processed: resuming does not retry
    # missing_doi or not_found automatically
    pmids = connection.execute(
        select(citation_enrichments.c.pmid)
        .where(citation_enrichments.c.run_id == run_id)
        .where(citation_enrichments.c.source == source)
    ).scalars()

    return set(pmids)


def load_enrichment_gaps(
    connection: Connection,
    run_id: str,
    source: str,
) -> list[dict]:
    # Absences already recorded by the source (no DOI or 404), candidates
    # to be complemented by another source. Citations the source has not
    # processed yet are not here: they are the difference between
    # load_citations() and get_enriched_pmids()
    rows = connection.execute(
        select(
            citation_enrichments.c.status,
            citations.c.pmid,
            citations.c.doi,
            citations.c.title,
        )
        .join(
            citations,
            (citations.c.run_id == citation_enrichments.c.run_id)
            & (citations.c.pmid == citation_enrichments.c.pmid),
        )
        .where(citation_enrichments.c.run_id == run_id)
        .where(citation_enrichments.c.source == source)
        .where(citation_enrichments.c.status.in_(["missing_doi", "not_found"]))
        .order_by(citation_enrichments.c.status, citations.c.pmid)
    ).mappings().all()

    return [dict(row) for row in rows]


def count_rows(connection: Connection) -> dict[str, int]:
    return {
        table.name: connection.execute(
            select(func.count()).select_from(table)
        ).scalar_one()
        for table in metadata.sorted_tables
    }


def load_raw_snapshot(
    connection: Connection,
    run_id: str,
    endpoint: str,
) -> dict | None:
    row = connection.execute(
        select(raw_snapshots)
        .where(raw_snapshots.c.run_id == run_id)
        .where(raw_snapshots.c.endpoint == endpoint)
    ).mappings().one_or_none()

    if row is None:
        return None

    snapshot = dict(row)

    # JSON was serialized on insert; XML is kept as stored text
    if snapshot["payload_format"] == "json":
        snapshot["payload"] = json.loads(snapshot["payload"])

    return snapshot
