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

PUBMED_QUERY = PUBMED_VARIANTS[PUBMED_ACTIVE_VARIANT]["query"]
