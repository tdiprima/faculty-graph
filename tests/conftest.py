"""Shared fixtures for the faculty-graph test suite."""

import pytest

from tests import fixtures


@pytest.fixture
def faculty_with_orcid():
    """A seed record that harvesters will search by ORCID iD."""
    return {
        "faculty_id": "fac-001",
        "full_name": "Ada Lovelace",
        "department": "Psychoceramics",
        "orcid": "0000-0002-1825-0097",
        "email": "ada@example.edu",
    }


@pytest.fixture
def faculty_without_orcid():
    """A seed record that falls back to name search, producing candidates."""
    return {
        "faculty_id": "fac-002",
        "full_name": "Grace Hopper",
        "department": "Psychoceramics",
        "orcid": "",
        "email": "grace@example.edu",
    }


@pytest.fixture
def raw_base(tmp_path):
    """An empty raw harvest tree with the directory layout the pipeline expects."""
    for source in ("orcid", "pubmed", "openalex"):
        (tmp_path / "raw" / source).mkdir(parents=True)
    return tmp_path / "raw"


@pytest.fixture
def seed_file(tmp_path):
    """Write a seed CSV and return its path."""
    def _write(rows):
        path = tmp_path / "faculty.csv"
        path.write_text(fixtures.seed_csv(rows), encoding="utf-8")
        return path
    return _write
