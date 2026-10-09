# Bibliometric RAG Assistant

An early-stage research project to collect bibliometric data from public APIs
(PubMed, with Crossref and OpenAlex planned) and, eventually, support an
LLM-based retrieval-augmented question-answering layer over the collected
literature.

The project is currently in its scaffolding phase: notebooks are being used to
explore each API integration, and the reusable logic is being progressively
modularized into an importable `src/bibliometric_rag_assistant` package. The
PubMed pipeline now runs end to end: search, fetch, parse, and persist into a
local SQLite database.


## Table of contents

- [About the project](#about-the-project)
  - [Research protocol](#research-protocol)
  - [Notebooks](#notebooks)
  - [Agents experiment](#agents-experiment)
- [Reproducibility](#reproducibility)
  - [Prerequisites](#prerequisites)
  - [Setup](#setup)
  - [Environment variables](#environment-variables)
  - [Ingesting a sample](#ingesting-a-sample)
  - [Running the notebooks](#running-the-notebooks)


## About the project

The first integration target is the [PubMed E-utilities API](https://www.ncbi.nlm.nih.gov/books/NBK25501/),
used to search and fetch bibliographic records for a defined search strategy.
The search strategy itself (query variants, active variant, date range, sample
size) is declared as data in `configs/search_strategy.yaml`, kept separate from
the code that reads it.

Current package modules:

| Module | Responsibility |
|---|---|
| `bibliometric_rag_assistant.config` | Project root, `.env` loading, environment variables, output directory paths |
| `bibliometric_rag_assistant.search_strategy` | Loads `configs/search_strategy.yaml`, composes each query variant with the configured date range, and resolves the active PubMed query (`PUBMED_QUERY`, `PUBMED_QUERIES`) |
| `bibliometric_rag_assistant.ingestion.pubmed` | PubMed E-utilities client: `search_pubmed()`, `fetch_pubmed_citations()`, `parse_pubmed_xml()`, `compare_queries()` |
| `bibliometric_rag_assistant.db` | SQLite persistence layer: `connect_database()`, `create_tables()`, `insert_ingestion_run()`, `insert_raw_snapshot()`, `insert_citations()`, `save_ingestion()`, `count_rows()` |

The database lives at `data/interim/bibliometria.db` and has three tables:

| Table | Content |
|---|---|
| `ingestion_runs` | One row per execution: source, query text, variant and version, timestamp, total results and total retrieved |
| `raw_snapshots` | The raw ESearch (JSON) and EFetch (XML) payloads of each run, plus the path of the copy saved under `data/raw/pubmed` |
| `citations` | Parsed records per run (pmid, doi, title, abstract, journal, publication year, language, authors and affiliations as JSON) |

`save_ingestion()` writes a run, its snapshots, and its citations in a single
transaction, rolling everything back if any insert fails.

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
| `notebooks/exploration/01_pubmed_sqlite_persistence_exploration.ipynb` | Prototype of the SQLite schema and insert functions later moved into `bibliometric_rag_assistant.db` |
| `notebooks/exploration/02_create_screening_sample.ipynb` | Exports the stored sample to `data/curated/pubmed_sample_screening.csv` for manual screening |
| `notebooks/validation/01_pubmed_ingestion_validation.ipynb` | Validates the refactored functions in `bibliometric_rag_assistant.ingestion.pubmed` |
| `notebooks/validation/02_pubmed_sqlite_validation.ipynb` | Validates `bibliometric_rag_assistant.db`: row counts, JSON round-trip, duplicate-run rejection, and foreign key integrity |

`exploration/` notebooks are where an idea is first tried out; `validation/`
notebooks import the code after it has been moved into `src/` and check that it
still behaves as expected.

### Agents experiment

`experiments/agents/etapa_0/00_pubmed_tool_loop.ipynb` is a hands-on study of
tool-calling agents, kept outside the importable package on purpose. It exposes
`search_pubmed` as a single read-only tool to an OpenAI model through a
hand-written agentic loop (no framework, no SDK-provided tool runner), capped at
two tool calls per run. Each run logs which tool was chosen, its arguments, a
summary of the result, and why the loop stopped (`end_turn` vs. `max_tool_calls`).

It's tested against three known questions: two that should make the agent call
`search_pubmed`, and one deliberately unrelated to PubMed ("What is the capital
of France?") to confirm the agent also knows when *not* to call a tool. This
experiment is the first step toward the project's intended end product: an
agentic RAG assistant over the collected literature.


## Reproducibility

### Prerequisites

- Python 3.12 (pinned in `.python-version`)
- [uv](https://docs.astral.sh/uv/) for dependency management and virtual environments
- An NCBI account email, required by the PubMed E-utilities API

### Setup

```bash
git clone <repo-url>
cd bibliometric-rag-assistant
uv sync
```

`uv sync` creates `.venv/`, installs the exact dependency versions pinned in
`uv.lock`, and installs this project itself in editable mode, so
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
| `OPENALEX_API_KEY` | No | Reserved for future OpenAlex ingestion. |
| `CROSSREF_MAILTO` | No | Reserved for future Crossref ingestion (polite pool). |
| `OPENAI_API_KEY` | No | Only needed to run the agents experiment (`experiments/agents/etapa_0/00_pubmed_tool_loop.ipynb`). |

Output directories (`data/raw/pubmed`, `data/raw/crossref`, `data/raw/openalex`,
`data/interim`) are created automatically the first time
`bibliometric_rag_assistant.config` is imported. The whole `data/` directory is
git-ignored.

### Ingesting a sample

```bash
uv run python scripts/ingest_sample.py
```

This runs the PubMed search defined by the `active_variant` entry in
`configs/search_strategy.yaml`, saves the raw ESearch and EFetch responses under
`data/raw/pubmed`, parses the citations, and stores the run in
`data/interim/bibliometria.db`. It prints a summary with the run id, the number
of results found and retrieved, the raw files written, and the row count of each
table. Each execution is stored as a new run, identified by its UTC timestamp.

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

`notebooks/validation/02_pubmed_sqlite_validation.ipynb` does the same and also
writes the result to the local database, so each run of it adds a new ingestion
run.
