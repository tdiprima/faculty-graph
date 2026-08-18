"""Generate static HTML previews of faculty publications from harvested data."""

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.provenance import SEARCH_METHOD_NAME, SEARCH_METHOD_ORCID

logger = logging.getLogger(__name__)

PUBMED_SEARCH_METHODS = (SEARCH_METHOD_ORCID, SEARCH_METHOD_NAME)

# PubMed writes one raw file per search method, so its raw_files keys carry a
# suffix ("pubmed:name") to stay unique. The suffix is display-only noise.
SOURCE_KEY_SEPARATOR = ":"


def _base_source(source_key):
    """Return the source name a raw_files key refers to, without its suffix."""
    return source_key.split(SOURCE_KEY_SEPARATOR, 1)[0]


def _read_json(path):
    """Read a raw JSON harvest file."""
    with open(path, encoding="utf-8") as infile:
        return json.load(infile)


def _parse_raw_file(source_name, path):
    """Parse one raw harvest file with the parser matching its source."""
    if source_name == "orcid":
        from src.harvest_orcid.parser import parse_works as parse_orcid
        return parse_orcid(_read_json(path))
    if source_name == "openalex":
        from src.harvest_openalex.parser import parse_works as parse_openalex
        return parse_openalex(_read_json(path))
    if source_name == "pubmed":
        from src.harvest_pubmed.parser import parse_pubmed_xml
        return parse_pubmed_xml(Path(path).read_text(encoding="utf-8"))

    logger.warning("No preview parser for source %s", source_name)
    return []


DOI_URL_PREFIXES = ("https://doi.org/", "http://doi.org/", "doi:")


def _normalize_doi(doi):
    """Reduce a DOI to its comparable form.

    DOIs are case-insensitive, and the sources disagree on case and on whether
    the resolver prefix is included, so the raw strings cannot be compared
    directly. Only the comparison key is normalized; the displayed DOI keeps
    whatever the source published.
    """
    if not doi:
        return ""
    normalized = str(doi).strip().lower()
    for prefix in DOI_URL_PREFIXES:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
            break
    return normalized.strip("/")


def _identity_keys(publication):
    """Return the identifiers that mark this publication as already seen.

    PubMed records often carry a PMID but no DOI, and the same record can arrive
    from both PubMed search methods, so PMID must dedupe alongside DOI.
    """
    keys = []
    doi = _normalize_doi(publication.get("doi"))
    if doi:
        keys.append(("doi", doi))
    pmid = str(publication.get("pmid") or "").strip()
    if pmid:
        keys.append(("pmid", pmid))
    return keys


def _load_faculty_publications(raw_files):
    """Load publications from the given {source_key: raw_file_path} mapping.

    Paths are resolved by the caller so this stays a pure read: the preview
    stage must never write into the raw harvest directory.
    """
    publications = []
    seen_identifiers = set()

    for source_key, path in raw_files.items():
        source_name = _base_source(source_key)
        try:
            parsed = _parse_raw_file(source_name, path)
        except json.JSONDecodeError as error:
            logger.error("Malformed raw %s file %s: %s", source_name, path, error)
            continue
        except OSError as error:
            logger.error("Cannot read raw %s file %s: %s", source_name, path, error)
            continue

        for pub in parsed:
            identity_keys = _identity_keys(pub)
            if any(key in seen_identifiers for key in identity_keys):
                continue
            seen_identifiers.update(identity_keys)
            pub["_source"] = source_name
            publications.append(pub)

    publications.sort(key=lambda p: p.get("date") or "0000", reverse=True)
    return publications


def _escape_html(text):
    """Escape HTML special characters."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def generate_faculty_html(faculty, publications):
    """Generate HTML preview for a single faculty member."""
    name = _escape_html(faculty["full_name"])
    department = _escape_html(faculty.get("department", ""))
    orcid = faculty.get("orcid", "")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    pub_rows = []
    for pub in publications:
        title = _escape_html(pub.get("title", "Untitled"))
        date = _escape_html(pub.get("date", ""))
        source = _escape_html(pub.get("_source", pub.get("source", "")))
        doi = pub.get("doi", "")
        doi_link = ""
        if doi:
            doi_link = f'<a href="https://doi.org/{_escape_html(doi)}">{_escape_html(doi)}</a>'

        journal = _escape_html(pub.get("journal", ""))
        pub_type = _escape_html(pub.get("type", ""))

        pub_rows.append(f"""        <tr>
            <td>{title}</td>
            <td>{journal}</td>
            <td>{date}</td>
            <td>{doi_link}</td>
            <td>{source}</td>
        </tr>""")

    publications_html = "\n".join(pub_rows) if pub_rows else "<tr><td colspan='5'>No publications found</td></tr>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>{name} - Publications</title>
    <style>
        body {{ font-family: system-ui, sans-serif; max-width: 1000px; margin: 2em auto; padding: 0 1em; color: #333; }}
        h1 {{ border-bottom: 2px solid #c41230; padding-bottom: 0.3em; }}
        .meta {{ color: #666; margin-bottom: 2em; }}
        .meta a {{ color: #1a5276; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 1em; }}
        th {{ background: #f5f5f5; text-align: left; padding: 0.5em; border-bottom: 2px solid #ddd; }}
        td {{ padding: 0.5em; border-bottom: 1px solid #eee; vertical-align: top; }}
        tr:hover {{ background: #fafafa; }}
        .count {{ font-size: 0.9em; color: #666; }}
        .footer {{ margin-top: 2em; font-size: 0.8em; color: #999; }}
    </style>
</head>
<body>
    <h1>{name}</h1>
    <div class="meta">
        <p>{department}</p>
        <p>ORCID: <a href="https://orcid.org/{orcid}">{orcid}</a></p>
    </div>

    <h2>Publications <span class="count">({len(publications)} total)</span></h2>
    <table>
        <thead>
            <tr>
                <th>Title</th>
                <th>Journal</th>
                <th>Date</th>
                <th>DOI</th>
                <th>Source</th>
            </tr>
        </thead>
        <tbody>
{publications_html}
        </tbody>
    </table>

    <div class="footer">
        Generated {timestamp} by faculty-graph pipeline.
    </div>
</body>
</html>"""


def _locate_raw_files(faculty, raw_base):
    """Map each source to this faculty member's raw harvest file, if present.

    ORCID files are named by ORCID iD, every other source by faculty_id. PubMed
    harvests one file per search method, so it contributes one key per file.
    """
    raw_files = {}

    orcid_id = faculty.get("orcid", "").strip()
    if orcid_id:
        orcid_path = raw_base / "orcid" / f"{orcid_id}.json"
        if orcid_path.exists():
            raw_files["orcid"] = orcid_path

    openalex_path = raw_base / "openalex" / f"{faculty['faculty_id']}.json"
    if openalex_path.exists():
        raw_files["openalex"] = openalex_path

    for search_method in PUBMED_SEARCH_METHODS:
        pubmed_path = (
            raw_base / "pubmed" / f"{faculty['faculty_id']}-{search_method}.xml"
        )
        if pubmed_path.exists():
            raw_files[f"pubmed{SOURCE_KEY_SEPARATOR}{search_method}"] = pubmed_path

    return raw_files


def generate_all_previews(seed_csv, raw_base_dir, output_dir):
    """Generate HTML preview pages for all faculty in seed list."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_base = Path(raw_base_dir)

    with open(seed_csv, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        faculty_list = list(reader)

    generated = 0
    for faculty in faculty_list:
        faculty_id = faculty["faculty_id"]
        raw_files = _locate_raw_files(faculty, raw_base)

        publications = _load_faculty_publications(raw_files)
        html = generate_faculty_html(faculty, publications)

        output_path = output_dir / f"{faculty_id}.html"
        with open(output_path, "w", encoding="utf-8") as outfile:
            outfile.write(html)

        logger.info("Generated preview: %s (%d pubs)", output_path, len(publications))
        generated += 1

    logger.info("Generated %d faculty preview pages in %s", generated, output_dir)


def main():
    """Generate previews from command line."""
    logging.basicConfig(
        level="INFO",
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    project_root = Path(__file__).resolve().parent.parent.parent
    seed_csv = project_root / "data" / "seed" / "faculty.csv"
    raw_base = project_root / "data" / "raw"
    output_dir = project_root / "data" / "output" / "previews"

    generate_all_previews(seed_csv, raw_base, output_dir)


if __name__ == "__main__":
    main()
