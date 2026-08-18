"""Builders for synthetic harvest payloads.

Tests construct raw source responses here rather than reading data/raw, so the
suite is deterministic and does not depend on a previous harvest.
"""

import json


def orcid_works(entries):
    """Build an ORCID /works response.

    entries: list of dicts with optional title, doi, pmid, year, month, day, type.
    """
    groups = []
    for entry in entries:
        external_ids = []
        if entry.get("doi"):
            external_ids.append(
                {"external-id-type": "doi", "external-id-value": entry["doi"]}
            )
        if entry.get("pmid"):
            external_ids.append(
                {"external-id-type": "pmid", "external-id-value": entry["pmid"]}
            )

        publication_date = None
        if entry.get("year"):
            publication_date = {"year": {"value": entry["year"]}}
            if entry.get("month"):
                publication_date["month"] = {"value": entry["month"]}
            if entry.get("day"):
                publication_date["day"] = {"value": entry["day"]}

        title = entry.get("title")
        groups.append({
            "external-ids": {"external-id": external_ids},
            "work-summary": [{
                "title": {"title": {"value": title}} if title else None,
                "type": entry.get("type", "journal-article"),
                "publication-date": publication_date,
                "put-code": entry.get("put_code", 1),
            }],
        })
    return {"group": groups, "path": "/0000-0000-0000-0000/works"}


def _openalex_institution(institution):
    """Build one authorship institution from a display name or a full dict."""
    if isinstance(institution, str):
        return {"display_name": institution}
    return dict(institution)


def openalex_works(entries, next_cursor=None):
    """Build an OpenAlex /works response."""
    results = []
    for entry in entries:
        work = {
            "id": f"https://openalex.org/{entry.get('openalex_id', 'W1')}",
            "title": entry.get("title"),
            "type": entry.get("type", "article"),
            "publication_date": entry.get("date"),
            "cited_by_count": entry.get("cited_by_count", 0),
            "ids": {},
            "authorships": [],
            "topics": [],
        }
        if entry.get("doi"):
            work["doi"] = f"https://doi.org/{entry['doi']}"
        if entry.get("pmid"):
            work["ids"]["pmid"] = f"https://pubmed.ncbi.nlm.nih.gov/{entry['pmid']}"
        if entry.get("journal"):
            work["primary_location"] = {
                "source": {
                    "display_name": entry["journal"],
                    "issn_l": entry.get("issn"),
                }
            }
        if any(entry.get(field) for field in ("volume", "issue", "first_page", "last_page")):
            work["biblio"] = {
                "volume": entry.get("volume"),
                "issue": entry.get("issue"),
                "first_page": entry.get("first_page"),
                "last_page": entry.get("last_page"),
            }
        for author in entry.get("authors", []):
            work["authorships"].append({
                "author": {
                    "display_name": author["name"],
                    "orcid": (
                        f"https://orcid.org/{author['orcid']}"
                        if author.get("orcid") else None
                    ),
                },
                "institutions": [
                    _openalex_institution(institution)
                    for institution in author.get("institutions", [])
                ],
                "is_corresponding": author.get("is_corresponding", False),
            })
        results.append(work)

    return {"results": results, "meta": {"next_cursor": next_cursor}}


def _pubmed_author(author):
    """Build one PubMed Author element.

    Accepts the legacy (fore, last) tuple or a dict adding orcid and
    affiliations.
    """
    if isinstance(author, dict):
        fore = author.get("fore", "")
        last = author.get("last", "")
        orcid = author.get("orcid")
        affiliations = author.get("affiliations", [])
    else:
        fore, last = author
        orcid = None
        affiliations = []

    parts = [f"<LastName>{last}</LastName><ForeName>{fore}</ForeName>"]
    if orcid:
        parts.append(f'<Identifier Source="ORCID">{orcid}</Identifier>')
    for affiliation in affiliations:
        parts.append(
            f"<AffiliationInfo><Affiliation>{affiliation}</Affiliation></AffiliationInfo>"
        )
    return f"<Author>{''.join(parts)}</Author>"


def _pubmed_journal_body(entry):
    """Build the Journal element body, including ISSN, volume, and issue."""
    parts = []
    if entry.get("issn"):
        parts.append(f"<ISSN>{entry['issn']}</ISSN>")

    issue_parts = []
    if entry.get("volume"):
        issue_parts.append(f"<Volume>{entry['volume']}</Volume>")
    if entry.get("issue"):
        issue_parts.append(f"<Issue>{entry['issue']}</Issue>")
    if issue_parts:
        parts.append(f"<JournalIssue>{''.join(issue_parts)}</JournalIssue>")

    parts.append(f"<Title>{entry.get('journal', '')}</Title>")
    return "".join(parts)


def _pubmed_pagination(entry):
    """Build the Pagination element, or nothing when no pages are given."""
    if not entry.get("pages"):
        return ""
    return f"<Pagination><MedlinePgn>{entry['pages']}</MedlinePgn></Pagination>"


def pubmed_xml(entries):
    """Build a PubMed efetch XML document."""
    articles = []
    for entry in entries:
        authors = "".join(_pubmed_author(author) for author in entry.get("authors", []))
        article_ids = "".join(
            f'<ArticleId IdType="{id_type}">{value}</ArticleId>'
            for id_type, value in entry.get("article_ids", {}).items()
        )
        date = ""
        if entry.get("year"):
            date = (
                f"<ArticleDate><Year>{entry['year']}</Year>"
                f"<Month>{entry.get('month', '01')}</Month>"
                f"<Day>{entry.get('day', '01')}</Day></ArticleDate>"
            )
        articles.append(
            "<PubmedArticle><MedlineCitation>"
            f"<PMID>{entry.get('pmid', '1')}</PMID>"
            "<Article>"
            f"<ArticleTitle>{entry.get('title', '')}</ArticleTitle>"
            f"<Journal>{_pubmed_journal_body(entry)}</Journal>"
            f"<AuthorList>{authors}</AuthorList>"
            f"{_pubmed_pagination(entry)}"
            f"{date}"
            "</Article></MedlineCitation>"
            f"<PubmedData><ArticleIdList>{article_ids}</ArticleIdList></PubmedData>"
            "</PubmedArticle>"
        )
    return f"<PubmedArticleSet>{''.join(articles)}</PubmedArticleSet>"


SEED_HEADER = "faculty_id,full_name,department,orcid,email"


def seed_csv(rows):
    """Build a faculty seed CSV from (faculty_id, name, dept, orcid, email) tuples."""
    lines = [SEED_HEADER]
    lines.extend(",".join(row) for row in rows)
    return "\n".join(lines) + "\n"


def write_json(path, payload):
    """Write a JSON payload, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def write_text(path, content):
    """Write a text payload, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
