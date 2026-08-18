"""Faculty Graph Pipeline - orchestrates harvesting, review, and RDF generation.

Usage:
    python3 main.py                     # Run all harvesters + RDF output
    python3 main.py --full              # Harvest + disambiguate + preview
    python3 main.py --source orcid      # Run ORCID only
    python3 main.py --source pubmed     # Run PubMed only
    python3 main.py --source openalex   # Run OpenAlex only
    python3 main.py --preview           # Generate HTML previews (standalone)
    python3 main.py --disambiguate      # Run LLM disambiguation (standalone)
    python3 main.py --reconcile         # Link records across sources (standalone)
    python3 main.py --query NAME        # Print one query, resolved from .env
    python3 main.py --write-queries     # Write every resolved query to disk

Configuration is read from the environment, with a .env file in the project root
loaded at startup. Copy .env.example to .env to get started.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from src.errors import ConfigError, SeedDataError

logger = logging.getLogger(__name__)


def load_configuration():
    """Read .env before any module reads the environment.

    Called first so that every later import sees the same configuration,
    including modules that read a value once at import time.
    """
    from src.config import load_env_file
    return load_env_file()


def setup_logging():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


def get_paths():
    project_root = Path(__file__).resolve().parent
    return {
        "seed_csv": project_root / "data" / "seed" / "faculty.csv",
        "seed_example_csv": project_root / "data" / "seed" / "faculty.csv.example",
        "reviews_yaml": project_root / "data" / "seed" / "reviews.yaml",
        "raw_orcid": project_root / "data" / "raw" / "orcid",
        "raw_pubmed": project_root / "data" / "raw" / "pubmed",
        "raw_openalex": project_root / "data" / "raw" / "openalex",
        "rdf_output": project_root / "data" / "output" / "rdf",
        "preview_output": project_root / "data" / "output" / "previews",
        "disambig_output": project_root / "data" / "output" / "disambiguation",
        "query_output": project_root / "data" / "output" / "queries",
        "raw_base": project_root / "data" / "raw",
    }


def run_harvest(sources, paths):
    """Run specified harvesters and generate RDF. Returns all_results for downstream use."""
    from src.harvest_orcid.client import load_seed_faculty, harvest_all as harvest_orcid
    from src.rdf_model.converter import convert_all_to_rdf
    from src.review.manager import ReviewManager

    faculty_list = load_seed_faculty(paths["seed_csv"])
    if not faculty_list:
        logger.error("No faculty found in %s", paths["seed_csv"])
        return None

    review_manager = ReviewManager(paths["reviews_yaml"])
    all_results = []

    if "orcid" in sources:
        logger.info("=== Harvesting ORCID ===")
        orcid_results = harvest_orcid(faculty_list, paths["raw_orcid"])
        all_results.extend(orcid_results)

    if "pubmed" in sources:
        logger.info("=== Harvesting PubMed ===")
        from src.harvest_pubmed.client import harvest_all as harvest_pubmed
        pubmed_results = harvest_pubmed(faculty_list, paths["raw_pubmed"])
        all_results.extend(pubmed_results)

    if "openalex" in sources:
        logger.info("=== Harvesting OpenAlex ===")
        from src.harvest_openalex.client import harvest_all as harvest_openalex
        openalex_results = harvest_openalex(faculty_list, paths["raw_openalex"])
        all_results.extend(openalex_results)

    if not all_results:
        logger.error("No data harvested from any source")
        return None

    logger.info("=== Generating RDF ===")
    convert_all_to_rdf(all_results, paths["rdf_output"], review_manager)

    total_pubs = sum(len(pubs) for _, pubs in all_results)
    logger.info("Harvest complete: %d total publication assertions", total_pubs)
    return all_results


def run_query(name):
    """Print one query with the configured values substituted in.

    Printed to stdout so it can be piped straight to a SPARQL endpoint:

        uv run python3 main.py --query collaborating-institutions | \
            curl -s http://localhost:3030/faculty/sparql \
                 --data-urlencode query@- -H "Accept: text/csv"
    """
    from src.queries import load_query
    print(load_query(name))


def run_write_queries(paths):
    """Write every query, resolved, so each can be opened and run as-is."""
    logger.info("=== Writing Resolved Queries ===")
    from src.queries import write_resolved_queries
    return write_resolved_queries(paths["query_output"])


def run_reconcile(paths):
    """Link records that different sources reported separately.

    Reads the harvest already on disk and writes only links, into their own
    graph. Nothing this stage produces overwrites what a source said, so a bad
    run is undone by deleting one file.
    """
    logger.info("=== Reconciling Sources ===")
    from src.harvest_orcid.client import load_seed_faculty
    from src.rdf_model.organizations import OrganizationRegistry
    from src.reconcile.loader import collect_organizations, load_publications
    from src.reconcile.writer import write_reconciliation

    faculty_list = load_seed_faculty(paths["seed_csv"])
    if not faculty_list:
        logger.error("No faculty found in %s", paths["seed_csv"])
        return None

    publications_by_faculty = {
        faculty["faculty_id"]: load_publications(faculty, paths)
        for faculty in faculty_list
    }

    all_publications = [
        publication
        for publications in publications_by_faculty.values()
        for publication in publications
    ]
    if not all_publications:
        logger.warning(
            "No harvested records found under %s. Run a harvest first.",
            paths["raw_base"],
        )
        return None

    registry = collect_organizations(
        faculty_list, publications_by_faculty, OrganizationRegistry()
    )

    return write_reconciliation(all_publications, registry.all(), paths["rdf_output"])


def run_preview(paths):
    """Generate HTML preview pages."""
    logger.info("=== Generating Previews ===")
    from src.consumers.preview import generate_all_previews
    generate_all_previews(paths["seed_csv"], paths["raw_base"], paths["preview_output"])


def run_disambiguate(paths):
    """Run LLM disambiguation on candidate publications from the raw harvest."""
    logger.info("=== Running LLM Disambiguation ===")
    from src.harvest_orcid.client import load_seed_faculty
    from src.disambiguate.loader import load_candidates, load_known_works
    from src.disambiguate.scorer import score_batch, save_scores

    faculty_list = load_seed_faculty(paths["seed_csv"])
    output_dir = Path(paths["disambig_output"])
    output_dir.mkdir(parents=True, exist_ok=True)

    for faculty in faculty_list:
        candidates = load_candidates(
            faculty, paths["raw_pubmed"], paths["raw_openalex"]
        )
        if not candidates:
            logger.info("No candidates to disambiguate for %s", faculty["full_name"])
            continue

        logger.info(
            "Disambiguating %d candidates for %s",
            len(candidates),
            faculty["full_name"],
        )
        known_works = load_known_works(faculty, paths["raw_orcid"])
        scores = score_batch(faculty, candidates, known_works)
        save_scores(scores, output_dir / f"{faculty['faculty_id']}-scores.json")

    logger.info("Disambiguation complete")


def parse_args():
    parser = argparse.ArgumentParser(description="Faculty Graph Pipeline")
    parser.add_argument(
        "--source",
        choices=["orcid", "pubmed", "openalex"],
        action="append",
        help="Harvest from specific source (can repeat). Default: all.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run everything: harvest (all sources unless --source given), disambiguate, reconcile, generate previews.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Generate HTML preview pages (standalone or with --full).",
    )
    parser.add_argument(
        "--disambiguate",
        action="store_true",
        help="Run LLM disambiguation on candidate matches (standalone or with --full).",
    )
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Link records across sources into their own graph (standalone or with --full).",
    )
    parser.add_argument(
        "--query",
        metavar="NAME",
        help="Print one SPARQL query to stdout with .env values substituted in.",
    )
    parser.add_argument(
        "--list-queries",
        action="store_true",
        help="List the available query names.",
    )
    parser.add_argument(
        "--write-queries",
        action="store_true",
        help="Write every resolved query to data/output/queries/.",
    )
    return parser.parse_args()


def main():
    load_configuration()
    setup_logging()
    args = parse_args()
    paths = get_paths()

    # Query rendering needs configuration but no harvest, so it runs before the
    # seed-file check that the pipeline stages depend on.
    if args.list_queries or args.query or args.write_queries:
        try:
            run_query_stages(args, paths)
        except ConfigError as error:
            logger.error("%s", error)
            sys.exit(1)
        return

    if not paths["seed_csv"].exists():
        logger.error(
            "Seed file not found: %s. Copy %s to that path and fill in your "
            "own faculty roster.",
            paths["seed_csv"],
            paths["seed_example_csv"],
        )
        sys.exit(1)

    try:
        run_pipeline(args, paths)
    except SeedDataError as error:
        logger.error("Invalid seed data: %s", error)
        sys.exit(1)
    except ConfigError as error:
        logger.error("Invalid configuration: %s", error)
        sys.exit(1)


def run_query_stages(args, paths):
    """Handle the query flags, which read configuration but no harvested data."""
    from src.queries import available_queries

    if args.list_queries:
        for name in available_queries():
            print(name)
    if args.query:
        run_query(args.query)
    if args.write_queries:
        run_write_queries(paths)


def run_post_harvest_stages(args, paths):
    """Run whichever post-harvest stages were requested, in dependency order.

    Reconciliation runs before previews so a preview reflects the links this run
    produced rather than the previous run's.
    """
    if args.disambiguate:
        run_disambiguate(paths)
    if args.reconcile:
        run_reconcile(paths)
    if args.preview:
        run_preview(paths)


def run_pipeline(args, paths):
    """Dispatch to the requested pipeline stages."""
    sources = args.source or ["orcid", "pubmed", "openalex"]

    if args.full:
        results = run_harvest(sources, paths)
        if not results:
            sys.exit(1)
        run_disambiguate(paths)
        run_reconcile(paths)
        run_preview(paths)
        logger.info("=== Full pipeline complete ===")
        return

    if args.preview or args.disambiguate or args.reconcile:
        run_post_harvest_stages(args, paths)
        return

    results = run_harvest(sources, paths)
    if not results:
        sys.exit(1)


if __name__ == "__main__":
    main()
