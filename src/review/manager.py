"""Manage human review decisions for publication assertions."""

import logging
from datetime import datetime
from pathlib import Path

from src.errors import ReviewDataError

logger = logging.getLogger(__name__)

try:
    import yaml
except ImportError:
    yaml = None


def _make_work_key(doi=None, pmid=None):
    """Build a canonical work key from identifiers."""
    if doi:
        return f"doi:{doi}"
    if pmid:
        return f"pmid:{pmid}"
    return None


def _require_review_key(entry, reviews_path, section):
    """Return (faculty_id, work_id) for a review entry, or raise with context.

    Raised instead of a bare KeyError so a malformed entry names the offending
    file and section rather than crashing with an unreadable traceback.
    """
    faculty_id = entry.get("faculty_id")
    work_id = entry.get("work_id")
    if not faculty_id or not work_id:
        raise ReviewDataError(
            f"{reviews_path} [{section}]: entry missing required key "
            f"'faculty_id' or 'work_id': {entry!r}"
        )
    return (faculty_id, work_id)


class ReviewManager:
    """Loads and applies human review decisions from a YAML file."""

    def __init__(self, reviews_path=None):
        self.rejections = {}
        self.verifications = {}
        if reviews_path:
            self.load(reviews_path)

    def load(self, reviews_path):
        """Load review decisions from YAML file."""
        reviews_path = Path(reviews_path)
        if not reviews_path.exists():
            logger.info("No reviews file at %s, skipping", reviews_path)
            return

        if yaml is None:
            logger.warning(
                "PyYAML not installed. Install with: pip install pyyaml. "
                "Skipping review file."
            )
            return

        with open(reviews_path, encoding="utf-8") as review_file:
            data = yaml.safe_load(review_file)

        if not data:
            return

        for rejection in data.get("rejections", []):
            key = _require_review_key(rejection, reviews_path, "rejections")
            self.rejections[key] = {
                "reason": rejection.get("reason", ""),
                "reviewed_by": rejection.get("reviewed_by", "human"),
                "reviewed_at": str(rejection.get("reviewed_at", "")),
            }

        for verification in data.get("verifications", []):
            key = _require_review_key(verification, reviews_path, "verifications")
            self.verifications[key] = {
                "reason": verification.get("reason", ""),
                "reviewed_by": verification.get("reviewed_by", "human"),
                "reviewed_at": str(verification.get("reviewed_at", "")),
            }

        logger.info(
            "Loaded %d rejections, %d verifications",
            len(self.rejections),
            len(self.verifications),
        )

    def get_review(self, faculty_id, publication):
        """Check if a review decision exists for this faculty+publication pair.

        Returns (status, review_dict) or (None, None) if no review exists.
        """
        work_key_doi = _make_work_key(doi=publication.get("doi"))
        work_key_pmid = _make_work_key(pmid=publication.get("pmid"))

        for work_key in [work_key_doi, work_key_pmid]:
            if not work_key:
                continue
            rejection_key = (faculty_id, work_key)
            if rejection_key in self.rejections:
                return "rejected", self.rejections[rejection_key]
            if rejection_key in self.verifications:
                return "verified", self.verifications[rejection_key]

        return None, None

    def apply_reviews(self, faculty_id, publications):
        """Apply review overrides to publication list. Modifies in place."""
        overridden = 0
        for pub in publications:
            status, review = self.get_review(faculty_id, pub)
            if status:
                pub["assertion_status"] = status
                pub["reviewed_by"] = review["reviewed_by"]
                pub["reviewed_at"] = review["reviewed_at"]
                pub["review_note"] = review["reason"]
                overridden += 1

        if overridden:
            logger.info(
                "Applied %d review overrides for %s",
                overridden,
                faculty_id,
            )
        return publications
