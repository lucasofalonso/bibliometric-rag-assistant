import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]

NCBI_EMAIL = os.getenv("NCBI_EMAIL")
NCBI_API_KEY = os.getenv("NCBI_API_KEY")
OPENALEX_API_KEY = os.getenv("OPENALEX_API_KEY")

if not NCBI_EMAIL:
    raise RuntimeError("Defina NCBI_EMAIL no arquivo .env")

RAW_PUBMED_DIR = PROJECT_ROOT / "data" / "raw" / "pubmed"
RAW_CROSSREF_DIR = PROJECT_ROOT / "data" / "raw" / "crossref"
RAW_OPENALEX_DIR = PROJECT_ROOT / "data" / "raw" / "openalex"
DB_PATH = PROJECT_ROOT / "data" / "interim" / "bibliometria.db"

for directory in [
    RAW_PUBMED_DIR,
    RAW_CROSSREF_DIR,
    RAW_OPENALEX_DIR,
    DB_PATH.parent,
]:
    directory.mkdir(parents=True, exist_ok=True)
