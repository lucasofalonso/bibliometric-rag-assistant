# Bibliometric RAG Assistant

An early-stage research project to collect bibliometric data from public APIs
(PubMed and Crossref, with OpenAlex planned) and, eventually, support an
LLM-based retrieval-augmented question-answering layer over the collected
literature.

Notebooks are used to explore each API integration, and the reusable logic is
progressively modularized into an importable `src/bibliometric_rag_assistant`
package. Two pipelines currently run end to end:

- **PubMed ingestion**: search, fetch, parse, and persist a sample into
  PostgreSQL, running in a local container.
- **Crossref enrichment**: complement the stored citations with Crossref
  metadata, recording which ones could not be enriched.

The first implementation of both pipelines, over a local SQLite database, is
kept runnable under `legacy/` (see [Legacy SQLite implementation](#legacy-sqlite-implementation)).

In parallel, a hand-written tool-calling agent over these sources is being
studied step by step, and can already be used from the terminal or the browser.


## Table of contents

- [About the project](#about-the-project)
  - [Package modules](#package-modules)
  - [Database](#database)
  - [Research protocol](#research-protocol)
  - [Notebooks](#notebooks)
  - [Agents study](#agents-study)
- [Reproducibility](#reproducibility)
  - [Prerequisites](#prerequisites)
  - [Setup](#setup)
  - [Environment variables](#environment-variables)
  - [Connecting to PostgreSQL](#connecting-to-postgresql)
  - [Ingesting a sample](#ingesting-a-sample)
  - [Enriching with Crossref](#enriching-with-crossref)
  - [Talking to the agent](#talking-to-the-agent)
  - [Running the notebooks](#running-the-notebooks)
  - [Legacy SQLite implementation](#legacy-sqlite-implementation)


## About the project

The first integration target is the [PubMed E-utilities API](https://www.ncbi.nlm.nih.gov/books/NBK25501/),
used to search and fetch bibliographic records for a defined search strategy.
The search strategy itself (query variants, active variant, date range, sample
size) is declared as data in `configs/search_strategy.yaml`, kept separate from
the code that reads it.

The stored citations are then enriched through the [Crossref REST API](https://api.crossref.org/swagger-ui/index.html),
queried by DOI in the polite pool. Crossref adds metadata PubMed does not
provide, such as publisher, print and online dates, volume/issue/pages, ISSN
types, ORCIDs and per-author affiliations, reference and citation counts, and
the DOIs of the cited references.

### Package modules

| Module | Responsibility |
|---|---|
| `bibliometric_rag_assistant.config` | Project root, `.env` loading, environment variables, output directory paths |
| `bibliometric_rag_assistant.settings` | PostgreSQL connection settings read from `.env` (`get_postgres_settings()`), independent of `config` |
| `bibliometric_rag_assistant.contracts` | Pydantic contracts shared by the agent, scripts and future API: `PubMedSearchArgs` (query and limit) and `PubMedCollectionResult` (return of a persisted collection) |
| `bibliometric_rag_assistant.search_strategy` | Loads `configs/search_strategy.yaml`, composes each query variant with the configured date range, and resolves the active PubMed query (`PUBMED_QUERY`, `PUBMED_QUERIES`) |
| `bibliometric_rag_assistant.ingestion.pubmed` | PubMed E-utilities client: `search_pubmed()`, `fetch_pubmed_citations()`, `parse_pubmed_xml()`, `compare_queries()` |
| `bibliometric_rag_assistant.ingestion.crossref` | Crossref client: `check_missing_dois()` and `split_citations_by_doi()` (separate citations with and without DOI before any request), `fetch_crossref_work()`, `fetch_crossref_works()` (batch, collecting 404s instead of failing), `parse_crossref_work()` |
| `bibliometric_rag_assistant.ingestion.openalex` | Placeholder for the planned OpenAlex integration |
| `bibliometric_rag_assistant.db_postgres` | PostgreSQL persistence layer (SQLAlchemy Core): engine, table definitions, `create_tables()`, transactional saves (`save_ingestion()`, `save_citation_enrichments()`), and reads (`get_latest_run_id()`, `get_ingestion_run()`, `load_citations()`, `get_enriched_pmids()`, `load_enrichment_gaps()`, `count_rows()`, `load_raw_snapshot()`) |
| `bibliometric_rag_assistant.services.pubmed_collection` | `collect_pubmed()`: runs a PubMed expression, fetches and parses the records, and saves the run in one transaction, returning a `PubMedCollectionResult` |
| `bibliometric_rag_assistant.services.crossref_enrichment` | `enrich_crossref_run()`: enriches the pending citations of a stored run with Crossref, resuming from what was already processed |
| `bibliometric_rag_assistant.agents.typed_agent_postgres` | PubMed/Crossref agent with typed tools, runnable as a terminal chat; uses the shared contracts and knows the study preset |
| `bibliometric_rag_assistant.agents.chat_app_postgres` | Browser chat interface (Gradio) for the same agent |
| `bibliometric_rag_assistant.legacy` | First SQLite implementation (`legacy.db`) and the first agent (`legacy.agents`), kept runnable |

`parse_crossref_work()` returns a normalized record with: `doi`, `title`,
`journal`, `publisher`, `document_type`, `publication_year` and
`publication_year_source` (which Crossref date field the year came from,
preferring print over online), `published_print`, `published_online`, `volume`,
`issue`, `page`, `language`, `issn`, `issn_types`, `authors`, `author_details`
(name, ORCID, sequence, affiliations), `reference_count`, `citation_count`, and
`reference_dois`. HTML entities in free text (`&amp;`) are decoded.

### Database

The database is PostgreSQL, run by the `db` service of `compose.yaml` and stored
in the `postgres_data` Docker volume. It has four tables:

| Table | Content |
|---|---|
| `ingestion_runs` | One row per PubMed execution: source, query text, variant and version (`NULL` for independent searches), timestamp, total results and total retrieved |
| `raw_snapshots` | The complete raw ESearch (JSON) and EFetch (XML) payloads of each run. No file copies are written: `file_path` is `NULL` |
| `citations` | Parsed records per run (pmid, doi, title, abstract, journal, publication year, language, authors and affiliations as JSON) |
| `citation_enrichments` | One row per citation and enrichment source: DOI, timestamp, `status` (`success`, `missing_doi` or `not_found`), the full API response (`raw_json`) and the `parse_crossref_work()` result (`normalized_json`) |

`citation_enrichments` is keyed by `(run_id, pmid, source)` and references
`citations`, so the same citation can later receive an OpenAlex enrichment
alongside the Crossref one. Keeping the full response as JSON preserves every
Crossref field without one column per field. Citations whose Crossref status is
not `success` are the enrichment gaps (`load_enrichment_gaps()`), the
candidates for OpenAlex to complement.

Saves are transactional: a run, its snapshots, and its citations are written
together or rolled back together, and the same applies to a batch of
enrichments.

A run is identified as a study variant only when its query is exactly one of
the complete preset expressions (period included) of
`configs/search_strategy.yaml`; any other query, including a reformulated
preset, is stored with `query_variant` and `query_version` as `NULL`.

Since the raw payloads exist only in the database, the `postgres_data` volume
is the single copy of each collection: `docker compose down -v` erases it.

**Schema migrations.** The schema is still created by `create_tables()`
(`metadata.create_all()`), and the one change made so far, allowing `NULL` in
`query_variant` and `query_version`, was applied with an `ALTER TABLE`
recorded in the persistence validation notebook. [Alembic](https://alembic.sqlalchemy.org/)
is in an initial study: `alembic.ini` and `alembic/` hold only the scaffold
generated by `alembic init`, not yet connected to `db_postgres.metadata` or to
`settings`, and with no migrations. Until it is adopted, do not run Alembic
commands against the project database.

### Research protocol

`docs/research_protocol.md` (in Portuguese) holds the provisional protocol
behind the search: the research question (infections associated with alloplastic
temporomandibular joint prostheses, 2000–2025), the PCC framework, the sources,
the provisional inclusion and exclusion criteria, and the screening dictionary
(`decision`, `reason_code`, `justification`, `reviewer`) used when manually
assessing records. The search strategy is still provisional and will be adjusted
after the manual assessment of the first 20-record sample.

### Notebooks

Notebooks are split by purpose:

| Notebook | Purpose |
|---|---|
| `notebooks/exploration/00_pubmed_eutils_exploration.ipynb` | First contact with the PubMed E-utilities API: query building, ESearch, EFetch, and XML parsing |
| `notebooks/exploration/03_crossref_enrichement_exploration.ipynb` | First contact with the Crossref API: queries one stored DOI (read from the legacy SQLite database), explores the response, saves it raw, and prototypes the parser |
| `notebooks/exploration/04_postgres_connection_exploration.ipynb` | Connection to the PostgreSQL container and prototype of the SQLAlchemy tables and inserts later moved into `bibliometric_rag_assistant.db_postgres` |
| `notebooks/validation/01_pubmed_ingestion_validation.ipynb` | Validates the refactored functions in `bibliometric_rag_assistant.ingestion.pubmed` |
| `notebooks/validation/04_postgres_persistence_validation.ipynb` | Validates `bibliometric_rag_assistant.db_postgres` with local fictitious data: schema (including the `ALTER TABLE` for nullable variant and version), JSON round-trip, NULLs, empty lists, rollback, and the read functions |
| `notebooks/validation/05_postgres_services_validation.ipynb` | Validates the collection and enrichment services and the two PostgreSQL scripts with small real PubMed and Crossref requests: preset identification, independent and empty searches, resumption, and counts |

`exploration/` notebooks are where an idea is first tried out; `validation/`
notebooks import the code after it has been moved into `src/` and check that it
still behaves as expected. The validation notebooks 04 and 05 delete the runs
they create and leave existing data untouched. The notebooks of the SQLite
implementation are listed in [Legacy SQLite implementation](#legacy-sqlite-implementation).

### Agents study

The agents study lives in `experiments/agents/`, organized in stages. Each
stage builds on the previous one, with no agent framework and no SDK-provided
tool runner: the agentic loop is written by hand over the OpenAI Responses API.

**Stage 0: a first tool-calling loop**

`etapa_0/00_pubmed_tool_loop.ipynb` exposes `search_pubmed` as a single
read-only tool, capped at two tool calls per run. Each run logs which tool was
chosen, its arguments, a summary of the result, and why the loop stopped
(`end_turn` vs. `max_tool_calls`). It is tested against three known questions:
two that should make the agent call `search_pubmed`, and one deliberately
unrelated to PubMed ("What is the capital of France?") to confirm the agent
also knows when *not* to call a tool.

**Stage 1: typed tools and evaluation**

`etapa_1/01_typed_tools.ipynb` gives each tool an explicit contract built with
Pydantic (accepted arguments, types, and limits; extra fields forbidden), which
both guides the model through the generated JSON schema and validates the
arguments before the tool runs. Invalid arguments are not raised as errors:
they are returned to the model as an `invalid_arguments` observation, and the
notebook shows the model correcting its own call from it. The stage ends with
an agent over three typed tools:

| Tool | Purpose |
|---|---|
| `search_pubmed` | Total number of matching records and a limited list of PMIDs |
| `get_pubmed_citations` | Title, DOI, journal and year for known PMIDs |
| `get_crossref_work` | Crossref metadata and reference/citation counts for a DOI |

The executor turns external failures into observations too (`not_found`,
`external_error`), and the tool budget is four calls per question.

`etapa_1/02_agent_evaluation.ipynb` evaluates this agent on ten tasks. Cases
01–05 use the real tools (search, a larger request, metadata by PMID, Crossref
by DOI, and chaining PubMed → Crossref). Cases 06–08 and 10 replace one tool
with a short simulated result or failure (empty search, publication without
DOI, record missing from Crossref, external timeout), and case 09 is an
invalid request from the user (zero PMIDs). Each trajectory (tools, arguments,
observations, final answer, stop reason) is inspected and recorded manually,
and the success rate (approved cases / 10) is the baseline for comparing the
next versions of the agent.

The resulting agent was then moved into the package as
`bibliometric_rag_assistant.legacy.agents.typed_agent`, which adds conversation
continuity (the history, including tool calls, carries over between
questions), and `bibliometric_rag_assistant.legacy.agents.chat_app`, a browser
interface for it. Its current version, `agents.typed_agent_postgres` and
`agents.chat_app_postgres`, keeps the same loop and tools, takes the search
contract from `bibliometric_rag_assistant.contracts`, and is instructed to use
the study query only as a preset and to build its own queries (concept groups,
Boolean operators, field tags, MeSH, explicit dates) for other subjects. This is
the first step toward the project's intended end product: an agentic RAG
assistant over the collected literature.


## Reproducibility

### Prerequisites

- Python 3.12 (pinned in `.python-version`)
- [uv](https://docs.astral.sh/uv/) for dependency management and virtual environments
- An NCBI account email, required by the PubMed E-utilities API
- An OpenAI API key, only for the agents

### Setup

```bash
git clone <repo-url>
cd bibliometric-rag-assistant
uv sync
```

`uv sync` creates `.venv/`, installs the exact dependency versions pinned in
`uv.lock` (including the `dev` group: Gradio, Jupyter kernel, pytest, ruff),
and installs this project itself in editable mode, so
`import bibliometric_rag_assistant` works from any notebook or script.

### Environment variables

```bash
cp .env.example .env
```

Then fill in `.env`:

| Variable | Required | Purpose |
|---|---|---|
| `NCBI_EMAIL` | Yes | Identifies the caller to PubMed E-utilities. `bibliometric_rag_assistant.config` raises an error at import time if it is missing. |
| `NCBI_API_KEY` | No | Raises the PubMed E-utilities rate limit when set. |
| `CROSSREF_MAILTO` | No | Contact email sent to Crossref to use its polite pool. Defaults to `NCBI_EMAIL`. |
| `OPENALEX_API_KEY` | No | Reserved for the planned OpenAlex integration. |
| `OPENAI_API_KEY` | For the agents | Needed by the agents notebooks, the terminal chat, and the browser chat. |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Yes | Database, user and password of the PostgreSQL container; read both by `compose.yaml` and by `bibliometric_rag_assistant.settings`. |
| `POSTGRES_HOST`, `POSTGRES_PORT` | Yes | Where the scripts reach the container from the host: `127.0.0.1` and `5432` with the provided `compose.yaml`. |

### Connecting to PostgreSQL

The database runs in Docker, so [Docker](https://docs.docker.com/get-docker/)
with Compose is also required. With `.env` filled in, start the `db` service of
`compose.yaml` (a `postgres:18` image) in the background:

```bash
docker compose up -d
docker compose ps
```

`docker compose ps` should show the service as `healthy`: the healthcheck runs
`pg_isready` every few seconds. Compose reads `POSTGRES_DB`, `POSTGRES_USER` and
`POSTGRES_PASSWORD` from `.env` to create the database and user on the first
start; changing them later does not alter an existing volume. The port is
published only on `127.0.0.1:5432`, so the database is not exposed to the
network.

The Python side connects with SQLAlchemy and the Psycopg 3 driver.
`settings.get_postgres_settings()` reads the five `POSTGRES_*` variables, and
`db_postgres.create_postgres_engine()` builds the
`postgresql+psycopg://user:password@host:port/database` URL from them. To check
the connection from the host:

```bash
uv run python -c "
from sqlalchemy import text
from bibliometric_rag_assistant.db_postgres import create_postgres_engine
engine = create_postgres_engine()
with engine.connect() as connection:
    print(connection.execute(text('SELECT current_database(), current_user')).one())
engine.dispose()
"
```

To open a `psql` session inside the container:

```bash
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

The tables are created by `db_postgres.create_tables()`, which the PostgreSQL
scripts call before running, so a fresh container needs no manual step.
`create_tables()` only creates missing tables and never alters existing ones; a
schema change on an existing database is applied with SQL and recorded in
`notebooks/validation/04_postgres_persistence_validation.ipynb` (see
[Database](#database)).

To stop the container:

```bash
docker compose down      # keeps the data in the postgres_data volume
docker compose down -v   # also deletes the volume and every stored run
```

Output directories (`data/raw/pubmed`, `data/raw/crossref`, `data/raw/openalex`,
`data/interim`) are created automatically the first time
`bibliometric_rag_assistant.config` is imported. The whole `data/` directory is
git-ignored.

### Ingesting a sample

```bash
uv run python scripts/ingest_sample_postgres.py
uv run python scripts/ingest_sample_postgres.py --limit 50
uv run python scripts/ingest_sample_postgres.py \
  --query '"temporomandibular joint"[Title/Abstract] AND ("2020/01/01"[Date - Publication] : "2020/12/31"[Date - Publication])' \
  --limit 10
```

Without `--query`, this runs the active preset of `configs/search_strategy.yaml`,
period included; without `--limit`, it uses the configured `sample_size`. The
arguments are validated by `PubMedSearchArgs` (non-empty query, limit from 1 to
10,000), and a custom query runs exactly as written, so any date filter must be
part of it.

The script calls `collect_pubmed()`, which runs ESearch, fetches the records
with EFetch (sent as POST, so long PMID lists fit), parses them, and saves the
run, both raw payloads and the citations in one transaction. A search with zero
results is still saved, with its ESearch snapshot and no EFetch. The summary
shows the run id (a UUID), whether the query matched a preset, the requested,
found, retrieved, parsed and saved counts, the warnings reported by PubMed (such
as phrases not found), and the row count of each table. A failure is reported
as an error with nothing saved, and the script exits with status 1.

### Enriching with Crossref

```bash
uv run python scripts/enrich_crossref_sample_postgres.py
uv run python scripts/enrich_crossref_sample_postgres.py --run-id <run_id>
```

This enriches the citations of a stored run (the most recent one, unless
`--run-id` is given) through `enrich_crossref_run()`:

1. checks that the run exists, loads its citations, and skips those already
   processed by Crossref (any status);
2. separates citations with and without DOI, recording the latter as `missing_doi`;
3. queries Crossref one DOI at a time, recording 404s as `not_found`;
4. stores the raw response and the `parse_crossref_work()` result of each
   success in `citation_enrichments`, with no JSON files written.

The summary lists, besides the counts, every citation of the run still without
Crossref metadata, read from the database, so it stays complete across
executions. If a connection error or an HTTP error other than 404 interrupts the
run, what was already collected is saved first, the affected citation stays
pending, and running the script again resumes from where it stopped.

### Talking to the agent

In the terminal, as a chat with Markdown rendering:

```bash
uv run python -m bibliometric_rag_assistant.agents.typed_agent_postgres
uv run python -m bibliometric_rag_assistant.agents.typed_agent_postgres \
  "Look up the DOI 10.7759/cureus.95806 in Crossref and report its counts."
```

The agent's tools still query the APIs without saving anything: registering the
persisted collection and enrichment as tools is the next step.

![Terminal chat with the PubMed/Crossref agent](docs/images/terminal_chat.svg)

The first question is optional. The conversation continues after each answer
until `exit` or Ctrl+D; `--verbose` shows each iteration and tool call. The
agent replies in the language of the question.

In the browser:

```bash
uv run python -m bibliometric_rag_assistant.agents.chat_app_postgres
```

This opens a chat at <http://127.0.0.1:7860>. Each tool call appears as a
collapsible block (arguments and status) above the answer, each browser tab
holds its own conversation, and clearing the chat starts a new one.

### Running the notebooks

Register a Jupyter kernel for the project's virtual environment (only needed once):

```bash
uv run python -m ipykernel install --user --name bibliometric-rag-assistant
```

Open `notebooks/validation/01_pubmed_ingestion_validation.ipynb` and select the
`bibliometric-rag-assistant` kernel. Running it top to bottom sends the PubMed
search defined by the `active_variant` entry in `configs/search_strategy.yaml`,
fetches the matching citations, and parses them into structured records (pmid,
doi, title, abstract, authors, affiliations).

`notebooks/validation/04_postgres_persistence_validation.ipynb` and
`notebooks/validation/05_postgres_services_validation.ipynb` need the PostgreSQL
container running. Notebook 04 uses only local fictitious data; notebook 05 sends
small real requests to PubMed and Crossref and runs the two PostgreSQL scripts.
Both delete the runs they create.

The agents notebooks in `experiments/agents/` call the OpenAI API and need
`OPENAI_API_KEY`.

### Legacy SQLite implementation

The first implementation, over the SQLite database at
`data/interim/bibliometria.db`, was replaced by the PostgreSQL one and is kept
runnable. It saves raw copies under `data/raw/pubmed` and `data/raw/crossref`
and identifies runs by their UTC timestamp.

| Path | Content |
|---|---|
| `src/bibliometric_rag_assistant/legacy/db.py` | SQLite persistence layer (`bibliometric_rag_assistant.legacy.db`) |
| `src/bibliometric_rag_assistant/legacy/agents/` | First typed-tools agent (`typed_agent`) and its Gradio interface (`chat_app`) |
| `scripts/legacy/` | `ingest_sample.py` and `enrich_crossref_sample.py` over SQLite |
| `notebooks/legacy/exploration/01_pubmed_sqlite_persistence_exploration.ipynb` | Prototype of the SQLite schema and insert functions later moved into `legacy.db` |
| `notebooks/legacy/exploration/02_create_screening_sample.ipynb` | Exports the SQLite sample to `data/curated/pubmed_sample_screening.csv` for manual screening |
| `notebooks/legacy/validation/02_pubmed_sqlite_validation.ipynb` | Validates `legacy.db`: row counts, JSON round-trip, duplicate-run rejection, and foreign key integrity; each run adds an ingestion run to the SQLite database |
| `notebooks/legacy/validation/03_crossref_enrichement_validation.ipynb` | Validates `ingestion.crossref` over the latest SQLite run: missing-DOI report, single and batch fetches, 404 handling, parser edge cases, and the enrichment constraints in an in-memory SQLite database |

```bash
uv run python scripts/legacy/ingest_sample.py
uv run python scripts/legacy/enrich_crossref_sample.py
uv run python scripts/legacy/enrich_crossref_sample.py --run-id 20261016T155946Z
uv run python -m bibliometric_rag_assistant.legacy.db
uv run python -m bibliometric_rag_assistant.legacy.agents.typed_agent
uv run python -m bibliometric_rag_assistant.legacy.agents.chat_app
```
