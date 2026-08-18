"""Generate static HTML previews of faculty publications from harvested data."""

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def _load_faculty_publications(faculty_id, raw_dirs):
    """Load parsed publication data from raw JSON files across all sources."""
    publications = []
    seen_dois = set()

    for source_name, raw_dir in raw_dirs.items():
        raw_dir = Path(raw_dir)
        json_path = raw_dir / f"{faculty_id}.json"
        if not json_path.exists():
            for candidate in raw_dir.glob(f"{faculty_id}*.json"):
                json_path = candidate
                break

        if not json_path.exists():
            continue

        with open(json_path, encoding="utf-8") as infile:
            data = json.load(infile)

        if source_name == "orcid":
            from src.harvest_orcid.parser import parse_works as parse_orcid
            pubs = parse_orcid(data)
        elif source_name == "openalex":
            from src.harvest_openalex.parser import parse_works as parse_openalex
            pubs = parse_openalex(data)
        else:
            continue

        for pub in pubs:
            doi = pub.get("doi")
            if doi and doi in seen_dois:
                continue
            if doi:
                seen_dois.add(doi)
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


def generate_all_previews(seed_csv, raw_base_dir, output_dir):
    """Generate HTML preview pages for all faculty in seed list."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_base = Path(raw_base_dir)

    raw_dirs = {}
    for source in ["orcid", "openalex"]:
        source_dir = raw_base / source
        if source_dir.exists():
            raw_dirs[source] = source_dir

    with open(seed_csv, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        faculty_list = list(reader)

    generated = 0
    for faculty in faculty_list:
        faculty_id = faculty["faculty_id"]

        orcid_raw = raw_base / "orcid" / f"{faculty.get('orcid', '')}.json"
        faculty_raw_dirs = {}
        if orcid_raw.exists():
            faculty_raw_dirs["orcid"] = raw_base / "orcid"
            import shutil
            symlink = raw_base / "orcid" / f"{faculty_id}.json"
            if not symlink.exists():
                shutil.copy2(orcid_raw, symlink)

        openalex_raw = raw_base / "openalex" / f"{faculty_id}.json"
        if openalex_raw.exists():
            faculty_raw_dirs["openalex"] = raw_base / "openalex"

        publications = _load_faculty_publications(faculty_id, faculty_raw_dirs)
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
