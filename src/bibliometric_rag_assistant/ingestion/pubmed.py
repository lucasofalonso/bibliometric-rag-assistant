import atexit
import re
from xml.etree import ElementTree as ET

import httpx

from bibliometric_rag_assistant.config import NCBI_API_KEY, NCBI_EMAIL

EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

client = httpx.Client(
    timeout=30,
    follow_redirects=True,
    headers={"User-Agent": f"bibliometric-rag-assistant/0.1 ({NCBI_EMAIL})"},
)

atexit.register(client.close)


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


def fetch_pubmed_citations(pmids: list[str]) -> str:
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
        "tool": "bibliometric_rag_assistant",
        "email": NCBI_EMAIL,
    }

    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY

    response = client.get(
        f"{EUTILS_BASE_URL}/efetch.fcgi",
        params=params,
    )
    response.raise_for_status()

    return response.text


def get_element_text(element) -> str | None:
    if element is None:
        return None

    text = "".join(element.itertext()).strip()
    return text or None


def extract_publication_year(article_node) -> int | None:
    year = article_node.findtext(
        "Journal/JournalIssue/PubDate/Year"
    )

    if year:
        return int(year)

    medline_date = article_node.findtext(
        "Journal/JournalIssue/PubDate/MedlineDate"
    )

    if medline_date:
        match = re.search(r"\b(19|20)\d{2}\b", medline_date)

        if match:
            return int(match.group())

    return None


def parse_pubmed_xml(xml_content: str) -> list[dict]:
    root = ET.fromstring(xml_content)
    records = []

    for pubmed_article in root.findall("PubmedArticle"):
        citation = pubmed_article.find("MedlineCitation")
        article = citation.find("Article")

        pmid = citation.findtext("PMID")
        title = get_element_text(article.find("ArticleTitle"))

        abstract_parts = []

        for abstract_element in article.findall(
            "Abstract/AbstractText"
        ):
            text = get_element_text(abstract_element)

            if not text:
                continue

            label = abstract_element.attrib.get("Label")

            if label:
                abstract_parts.append(f"{label}: {text}")
            else:
                abstract_parts.append(text)

        authors = []

        for author in article.findall("AuthorList/Author"):
            collective_name = author.findtext("CollectiveName")

            if collective_name:
                authors.append(collective_name)
                continue

            first_name = author.findtext("ForeName") or ""
            last_name = author.findtext("LastName") or ""

            full_name = f"{first_name} {last_name}".strip()

            if full_name:
                authors.append(full_name)

        affiliations = sorted(
            {
                affiliation.text.strip()
                for affiliation in article.findall(
                    "AuthorList/Author/AffiliationInfo/Affiliation"
                )
                if affiliation.text
            }
        )

        doi = None

        for article_id in pubmed_article.findall(
            "PubmedData/ArticleIdList/ArticleId"
        ):
            if article_id.attrib.get("IdType") == "doi":
                doi = article_id.text
                break

        records.append(
            {
                "pmid": pmid,
                "doi": doi,
                "title": title,
                "abstract": "\n".join(abstract_parts) or None,
                "journal": article.findtext("Journal/Title"),
                "publication_year": extract_publication_year(article),
                "language": article.findtext("Language"),
                "authors": authors,
                "affiliations": affiliations,
            }
        )

    return records


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
