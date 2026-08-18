"""Faculty Graph Pipeline - orchestrates harvesting, review, and RDF generation.

Usage:
    python main.py                     # Run all harvesters
    python main.py --source orcid      # Run ORCID only
    python main.py --source pubmed     # Run PubMed only
    python main.py --source openalex   # Run OpenAlex only
    python main.py --preview           # Generate HTML previews
    python main.py --disambiguate      # Run LLM disambiguation on candidates
"""

import argparse
import logging
import os
import sys
from pathlib import Path

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
    """Run specified harvesters and generate RDF."""
    from src.harvest_orcid.client import load_seed_faculty, harvest_all as harvest_orcid
    from src.rdf_model.converter import convert_all_to_rdf
    from src.review.manager import ReviewManager

    faculty_list = load_seed_faculty(paths["seed_csv"])
    if not faculty_list:
        logger.error("No faculty found in %s", paths["seed_csv"])
        return False

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
        return False

    logger.info("=== Generating RDF ===")
    convert_all_to_rdf(all_results, paths["rdf_output"], review_manager)

    total_pubs = sum(len(pubs) for _, pubs in all_results)
    logger.info("Pipeline complete: %d total publication assertions", total_pubs)
    return True


def run_preview(paths):
    """Generate HTML preview pages."""
    from src.consumers.preview import generate_all_previews
    generate_all_previews(paths["seed_csv"], paths["raw_base"], paths["preview_output"])


def run_disambiguate(paths):
    """Run LLM disambiguation on candidate publications."""
    from src.harvest_orcid.client import load_seed_faculty, harvest_all as harvest_orcid
    from src.harvest_orcid.parser import parse_works
    from src.disambiguate.scorer import score_batch, save_scores
    import json

    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.error("ANTHROPIC_API_KEY not set. Cannot run disambiguation.")
        sys.exit(1)

    faculty_list = load_seed_faculty(paths["seed_csv"])
    output_dir = Path(paths["disambig_output"])
    output_dir.mkdir(parents=True, exist_ok=True)

    for faculty in faculty_list:
        faculty_id = faculty["faculty_id"]

        orcid_known = []
        orcid_raw = paths["raw_orcid"] / f"{faculty.get('orcid', '')}.json"
        if orcid_raw.exists():
            with open(orcid_raw, encoding="utf-8") as infile:
                orcid_known = parse_works(json.load(infile))

        candidates = []
        for source_dir in [paths["raw_pubmed"], paths["raw_openalex"]]:
            for candidate_file in source_dir.glob(f"{faculty_id}*.json"):
                with open(candidate_file, encoding="utf-8") as infile:
                    data = json.load(infile)
                if "results" in data:
                    from src.harvest_openalex.parser import parse_works as parse_oa
                    candidates.extend(parse_oa(data))

        candidates = [c for c in candidates if c.get("assertion_status") == "candidate"]

        if not candidates:
            logger.info("No candidates to disambiguate for %s", faculty["full_name"])
            continue

        logger.info(
            "Disambiguating %d candidates for %s",
            len(candidates),
            faculty["full_name"],
        )
        scores = score_batch(faculty, candidates, orcid_known)
        save_scores(scores, output_dir / f"{faculty_id}-scores.json")

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
        "--preview",
        action="store_true",
        help="Generate HTML preview pages.",
    )
    parser.add_argument(
        "--disambiguate",
        action="store_true",
        help="Run LLM disambiguation on candidate matches.",
    )
    return parser.parse_args()


def main():
    setup_logging()
    args = parse_args()
    paths = get_paths()

    if not paths["seed_csv"].exists():
        logger.error("Seed file not found: %s", paths["seed_csv"])
        sys.exit(1)

    if args.preview:
        run_preview(paths)
        return

    if args.disambiguate:
        run_disambiguate(paths)
        return

    sources = args.source or ["orcid", "pubmed", "openalex"]
    success = run_harvest(sources, paths)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
