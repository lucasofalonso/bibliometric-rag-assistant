import httpx

from bibliometric_rag_assistant.config import NCBI_API_KEY, NCBI_EMAIL

EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

client = httpx.Client(
    timeout=30,
    follow_redirects=True,
    headers={"User-Agent": f"bibliometric-rag-assistant/0.1 ({NCBI_EMAIL})"},
)


def search_pubmed(query: str, limit: int = 20) -> dict:
    params = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": limit,
        "tool": "bibliometric_rag_assistant",
        "email": NCBI_EMAIL,
    }

    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY

    response = client.get(
        f"{EUTILS_BASE_URL}/esearch.fcgi",
        params=params,
    )
    response.raise_for_status()

    return response.json()


def compare_queries(queries: dict[str, str]) -> dict[str, dict]:
    results = {}

    for name, query_text in queries.items():
        esearch = search_pubmed(query_text, limit=0)["esearchresult"]

        results[name] = {
            "total": int(esearch["count"]),
            "query_translation": esearch.get("querytranslation"),
            "warnings": esearch.get("warninglist"),
            "errors": esearch.get("errorlist"),
        }

    return results
