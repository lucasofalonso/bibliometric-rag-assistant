import atexit
import html
from urllib.parse import quote

import httpx

from bibliometric_rag_assistant.config import CROSSREF_MAILTO

CROSSREF_BASE_URL = "https://api.crossref.org"

client = httpx.Client(
    timeout=30,
    follow_redirects=True,
    headers={"User-Agent": f"bibliometric-rag-assistant/0.1 ({CROSSREF_MAILTO})"},
)

atexit.register(client.close)


def split_citations_by_doi(
    citations: list[dict],
) -> tuple[list[dict], list[dict]]:
    citations_with_doi = []
    citations_without_doi = []

    for citation in citations:
        doi = (citation.get("doi") or "").strip()

        if doi:
            citations_with_doi.append({**citation, "doi": doi})
        else:
            citations_without_doi.append(citation)

    return citations_with_doi, citations_without_doi


def check_missing_dois(citations: list[dict]) -> dict:
    citations_with_doi, citations_without_doi = split_citations_by_doi(
        citations
    )

    return {
        "total": len(citations),
        "with_doi": len(citations_with_doi),
        "without_doi": len(citations_without_doi),
        "missing": [
            {
                "pmid": citation.get("pmid"),
                "title": citation.get("title"),
            }
            for citation in citations_without_doi
        ],
        "citations_with_doi": citations_with_doi,
    }


def fetch_crossref_work(doi: str) -> dict:
    response = client.get(
        f"{CROSSREF_BASE_URL}/works/{quote(doi, safe='')}",
        params={"mailto": CROSSREF_MAILTO},
    )
    response.raise_for_status()

    return response.json()


def fetch_crossref_works(
    citations_with_doi: list[dict],
) -> tuple[dict[str, dict], list[str]]:
    responses = {}
    not_found = []

    for citation in citations_with_doi:
        doi = citation["doi"]

        try:
            responses[doi] = fetch_crossref_work(doi)
        except httpx.HTTPStatusError as error:
            # DOIs registered with other agencies (DataCite, mEDRA...)
            # do not exist in Crossref and return 404
            if error.response.status_code != 404:
                raise

            not_found.append(doi)

    return responses, not_found


def unescape_text(value: str | None) -> str | None:
    # Crossref returns HTML entities in free text ("&amp;" -> "&")
    if value is None:
        return None

    return html.unescape(value)


def first_item(values: list | None):
    if not values:
        return None

    return values[0]


def get_date_parts(work: dict, field: str) -> list[int] | None:
    date_parts = work.get(field, {}).get("date-parts", [])

    if date_parts and date_parts[0] and date_parts[0][0]:
        return [int(part) for part in date_parts[0] if part]

    return None


def format_crossref_date(work: dict, field: str) -> str | None:
    # [2024, 4] -> "2024-04"; [2023, 5, 28] -> "2023-05-28"
    date_parts = get_date_parts(work, field)

    if not date_parts:
        return None

    return "-".join(f"{part:02d}" for part in date_parts)


def extract_crossref_year(work: dict) -> tuple[int | None, str | None]:
    for field in [
        "published-print",
        "published-online",
        "published",
        "issued",
    ]:
        date_parts = work.get(field, {}).get("date-parts", [])

        if date_parts and date_parts[0] and date_parts[0][0]:
            return int(date_parts[0][0]), field

    return None, None


def parse_crossref_author(author: dict) -> dict:
    given = unescape_text(author.get("given"))
    family = unescape_text(author.get("family"))

    # Institutional authors come in "name" instead of given/family
    name = unescape_text(author.get("name")) or " ".join(
        part for part in [given, family] if part
    )

    return {
        "name": name or None,
        "given": given,
        "family": family,
        "sequence": author.get("sequence"),
        "orcid": author.get("ORCID"),
        "affiliations": [
            unescape_text(affiliation["name"])
            for affiliation in author.get("affiliation", [])
            if affiliation.get("name")
        ],
    }


def parse_crossref_work(work: dict) -> dict:
    # Authors without a name are dropped, keeping authors and
    # author_details aligned position by position
    author_details = [
        details
        for details in map(parse_crossref_author, work.get("author", []))
        if details["name"]
    ]

    publication_year, publication_year_source = extract_crossref_year(work)

    return {
        "doi": work.get("DOI"),
        "title": unescape_text(first_item(work.get("title"))),
        "journal": unescape_text(first_item(work.get("container-title"))),
        "publisher": unescape_text(work.get("publisher")),
        "document_type": work.get("type"),
        "publication_year": publication_year,
        "publication_year_source": publication_year_source,
        "published_print": format_crossref_date(work, "published-print"),
        "published_online": format_crossref_date(work, "published-online"),
        "volume": work.get("volume"),
        "issue": work.get("issue"),
        "page": work.get("page"),
        "language": work.get("language"),
        "issn": work.get("ISSN", []),
        "issn_types": work.get("issn-type", []),
        "authors": [details["name"] for details in author_details],
        "author_details": author_details,
        "reference_count": work.get("reference-count"),
        "citation_count": work.get("is-referenced-by-count"),
        # Only present when the publisher deposits the references openly
        "reference_dois": [
            reference["DOI"]
            for reference in work.get("reference", [])
            if reference.get("DOI")
        ],
    }
