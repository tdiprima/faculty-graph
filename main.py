"""Faculty Graph Pipeline - orchestrates harvesting, review, and RDF generation.

Usage:
    python3 main.py                     # Run all harvesters + RDF output
    python3 main.py --full              # Harvest + disambiguate + preview
    python3 main.py --source orcid      # Run ORCID only
    python3 main.py --source pubmed     # Run PubMed only
    python3 main.py --source openalex   # Run OpenAlex only
    python3 main.py --preview           # Generate HTML previews (standalone)
    python3 main.py --disambiguate      # Run LLM disambiguation (standalone)
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from src.errors import SeedDataError

logger = logging.getLogger(__name__)


def setup_logging():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


def get_paths():
    project_root = Path(__file__).resolve().parent
    return {
        "seed_csv": project_root / "data" / "seed" / "faculty.csv",
        "reviews_yaml": project_root / "data" / "seed" / "reviews.yaml",
        "raw_orcid": project_root / "data" / "raw" / "orcid",
        "raw_pubmed": project_root / "data" / "raw" / "pubmed",
        "raw_openalex": project_root / "data" / "raw" / "openalex",
        "rdf_output": project_root / "data" / "output" / "rdf",
        "preview_output": project_root / "data" / "output" / "previews",
        "disambig_output": project_root / "data" / "output" / "disambiguation",
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
        help="Run everything: harvest all sources, disambiguate, generate previews.",
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
    return parser.parse_args()


def main():
    setup_logging()
    args = parse_args()
    paths = get_paths()

    if not paths["seed_csv"].exists():
        logger.error("Seed file not found: %s", paths["seed_csv"])
        sys.exit(1)

    try:
        run_pipeline(args, paths)
    except SeedDataError as error:
        logger.error("Invalid seed data: %s", error)
        sys.exit(1)


def run_pipeline(args, paths):
    """Dispatch to the requested pipeline stages."""
    if args.full:
        sources = args.source or ["orcid", "pubmed", "openalex"]
        results = run_harvest(sources, paths)
        if not results:
            sys.exit(1)
        run_disambiguate(paths)
        run_preview(paths)
        logger.info("=== Full pipeline complete ===")
        return

    if args.preview and not args.disambiguate:
        run_preview(paths)
        return

    if args.disambiguate and not args.preview:
        run_disambiguate(paths)
        return

    if args.preview and args.disambiguate:
        run_disambiguate(paths)
        run_preview(paths)
        return

    sources = args.source or ["orcid", "pubmed", "openalex"]
    results = run_harvest(sources, paths)
    if not results:
        sys.exit(1)


if __name__ == "__main__":
    main()
