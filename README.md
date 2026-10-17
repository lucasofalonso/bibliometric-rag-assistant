# Bibliometric RAG Assistant

An early-stage research project to collect bibliometric data from public APIs
(PubMed and Crossref, with OpenAlex planned) and, eventually, support an
LLM-based retrieval-augmented question-answering layer over the collected
literature.

Notebooks are used to explore each API integration, and the reusable logic is
progressively modularized into an importable `src/bibliometric_rag_assistant`
package. Two pipelines currently run end to end:

- **PubMed ingestion**: search, fetch, parse, and persist a sample into a local
  SQLite database.
- **Crossref enrichment**: complement the stored citations with Crossref
  metadata, recording which ones could not be enriched.

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
  - [Ingesting a sample](#ingesting-a-sample)
  - [Enriching with Crossref](#enriching-with-crossref)
  - [Talking to the agent](#talking-to-the-agent)
  - [Running the notebooks](#running-the-notebooks)


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
| `bibliometric_rag_assistant.search_strategy` | Loads `configs/search_strategy.yaml`, composes each query variant with the configured date range, and resolves the active PubMed query (`PUBMED_QUERY`, `PUBMED_QUERIES`) |
| `bibliometric_rag_assistant.ingestion.pubmed` | PubMed E-utilities client: `search_pubmed()`, `fetch_pubmed_citations()`, `parse_pubmed_xml()`, `compare_queries()` |
| `bibliometric_rag_assistant.ingestion.crossref` | Crossref client: `check_missing_dois()` and `split_citations_by_doi()` (separate citations with and without DOI before any request), `fetch_crossref_work()`, `fetch_crossref_works()` (batch, collecting 404s instead of failing), `parse_crossref_work()` |
| `bibliometric_rag_assistant.ingestion.openalex` | Placeholder for the planned OpenAlex integration |
| `bibliometric_rag_assistant.db` | SQLite persistence layer: table creation, inserts, transactional saves (`save_ingestion()`, `save_citation_enrichments()`), and reads (`get_latest_run_id()`, `load_citations()`, `get_enriched_pmids()`, `load_enrichment_gaps()`, `count_rows()`) |
| `bibliometric_rag_assistant.agents.typed_agent` | PubMed/Crossref agent with typed tools, runnable as a terminal chat |
| `bibliometric_rag_assistant.agents.chat_app` | Browser chat interface (Gradio) for the same agent |

`parse_crossref_work()` returns a normalized record with: `doi`, `title`,
`journal`, `publisher`, `document_type`, `publication_year` and
`publication_year_source` (which Crossref date field the year came from,
preferring print over online), `published_print`, `published_online`, `volume`,
`issue`, `page`, `language`, `issn`, `issn_types`, `authors`, `author_details`
(name, ORCID, sequence, affiliations), `reference_count`, `citation_count`, and
`reference_dois`. HTML entities in free text (`&amp;`) are decoded.

### Database

The database lives at `data/interim/bibliometria.db` and has four tables:

| Table | Content |
|---|---|
| `ingestion_runs` | One row per PubMed execution: source, query text, variant and version, timestamp, total results and total retrieved |
| `raw_snapshots` | The raw ESearch (JSON) and EFetch (XML) payloads of each run, plus the path of the copy saved under `data/raw/pubmed` |
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
| `notebooks/exploration/03_crossref_enrichement_exploration.ipynb` | First contact with the Crossref API: queries one stored DOI, explores the response, saves it raw, and prototypes the parser |
| `notebooks/validation/01_pubmed_ingestion_validation.ipynb` | Validates the refactored functions in `bibliometric_rag_assistant.ingestion.pubmed` |
| `notebooks/validation/02_pubmed_sqlite_validation.ipynb` | Validates `bibliometric_rag_assistant.db`: row counts, JSON round-trip, duplicate-run rejection, and foreign key integrity |
| `notebooks/validation/03_crossref_enrichement_validation.ipynb` | Validates `bibliometric_rag_assistant.ingestion.crossref` and the enrichment persistence: missing-DOI report, single and batch fetches, 404 handling, parser edge cases, and the `citation_enrichments` constraints |

`exploration/` notebooks are where an idea is first tried out; `validation/`
notebooks import the code after it has been moved into `src/` and check that it
still behaves as expected.

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
`bibliometric_rag_assistant.agents.typed_agent`, which adds conversation
continuity (the history, including tool calls, carries over between
questions), and `bibliometric_rag_assistant.agents.chat_app`, a browser
interface for it. This is the first step toward the project's intended end
product: an agentic RAG assistant over the collected literature.


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

### Enriching with Crossref

```bash
uv run python scripts/enrich_crossref_sample.py
uv run python scripts/enrich_crossref_sample.py --run-id 20261016T155946Z
```

This enriches the citations of a PubMed run (the most recent one, unless
`--run-id` is given):

1. loads the run's citations and skips those already enriched;
2. separates citations with and without DOI, recording the latter as `missing_doi`;
3. queries Crossref one DOI at a time, recording 404s as `not_found`;
4. saves each raw response as `data/raw/crossref/<run_id>/<pmid>.json`;
5. parses the responses and stores every result in `citation_enrichments`.

The summary lists, besides the counts, every citation of the run still without
Crossref metadata, read from the database, so it stays complete across
executions. If an unexpected error (such as a 5xx) interrupts the run, what was
already collected is saved first, and running the script again resumes from
where it stopped.

### Talking to the agent

In the terminal, as a chat with Markdown rendering:

```bash
uv run python -m bibliometric_rag_assistant.agents.typed_agent
uv run python -m bibliometric_rag_assistant.agents.typed_agent \
  "Look up the DOI 10.7759/cureus.95806 in Crossref and report its counts."
```

![Terminal chat with the PubMed/Crossref agent](docs/images/terminal_chat.svg)

The first question is optional. The conversation continues after each answer
until `exit` or Ctrl+D; `--verbose` shows each iteration and tool call. The
agent replies in the language of the question.

In the browser:

```bash
uv run python -m bibliometric_rag_assistant.agents.chat_app
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

`notebooks/validation/02_pubmed_sqlite_validation.ipynb` does the same and also
writes the result to the local database, so each run of it adds a new ingestion
run.

`notebooks/validation/03_crossref_enrichement_validation.ipynb` reads the
citations of the most recent run (run `scripts/ingest_sample.py` first) and
queries Crossref for a small sample. It writes nothing to the project database:
the persistence checks run against an in-memory SQLite database.

The agents notebooks in `experiments/agents/` call the OpenAI API and need
`OPENAI_API_KEY`.
