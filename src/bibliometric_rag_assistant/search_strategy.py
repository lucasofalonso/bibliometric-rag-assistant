import yaml

from bibliometric_rag_assistant.config import PROJECT_ROOT

SEARCH_STRATEGY_PATH = PROJECT_ROOT / "configs" / "search_strategy.yaml"

with SEARCH_STRATEGY_PATH.open(encoding="utf-8") as file:
    _search_strategy = yaml.safe_load(file)

PUBMED_STRATEGY = _search_strategy["pubmed"]

PUBMED_STATUS = PUBMED_STRATEGY["status"]
PUBMED_PERIOD = PUBMED_STRATEGY["period"]
PUBMED_SAMPLE_SIZE = PUBMED_STRATEGY["sample_size"]
PUBMED_VARIANTS = PUBMED_STRATEGY["variants"]
PUBMED_ACTIVE_VARIANT = PUBMED_STRATEGY["active_variant"]
PUBMED_SOURCE = PUBMED_STRATEGY["source"]

def _pubmed_date_filter(period: dict) -> str:
    start = period["start"].replace("-", "/")
    end = period["end"].replace("-", "/")
    return f'( "{start}"[Date - Publication] : "{end}"[Date - Publication] )'


def build_pubmed_query(variant_name: str) -> str:
    thematic_query = PUBMED_VARIANTS[variant_name]["query"]
    return f"{thematic_query} AND {_pubmed_date_filter(PUBMED_PERIOD)}"


PUBMED_QUERY = build_pubmed_query(PUBMED_ACTIVE_VARIANT)
PUBMED_QUERIES = {name: build_pubmed_query(name) for name in PUBMED_VARIANTS}
