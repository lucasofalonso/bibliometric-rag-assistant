# Bibliometric RAG Assistant

An early-stage research project to collect bibliometric data from public APIs
(PubMed, with Crossref and OpenAlex planned) and, eventually, support an
LLM-based retrieval-augmented question-answering layer over the collected
literature.

The project is currently in its scaffolding phase: notebooks are being used to
explore each API integration, and the reusable logic is being progressively
modularized into an importable `src/bibliometric_rag_assistant` package.


## Table of contents

- [About the project](#about-the-project)
- [Reproducibility](#reproducibility)
  - [Prerequisites](#prerequisites)
  - [Setup](#setup)
  - [Environment variables](#environment-variables)
  - [Running the notebook](#running-the-notebook)


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
| `bibliometric_rag_assistant.search_strategy` | Loads `configs/search_strategy.yaml` and resolves the active PubMed query |
| `bibliometric_rag_assistant.ingestion.pubmed` | PubMed E-utilities client: `search_pubmed()`, `compare_queries()` |


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

Output directories (`data/raw/pubmed`, `data/raw/crossref`, `data/raw/openalex`,
`data/interim`) are created automatically the first time
`bibliometric_rag_assistant.config` is imported.

### Running the notebook

Register a Jupyter kernel for the project's virtual environment (only needed once):

```bash
uv run python -m ipykernel install --user --name bibliometric-rag-assistant
```

Open `notebooks/01_api_tests.ipynb` and select the `bibliometric-rag-assistant`
kernel. Running it top to bottom sends the PubMed search defined by the
`active_variant` entry in `configs/search_strategy.yaml` and prints the raw
E-utilities response.
