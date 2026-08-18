"""Seed CSV validation. The seed list is the pipeline's only untrusted input."""

import pytest

from src.errors import SeedDataError
from src.harvest_orcid.client import load_seed_faculty
from tests import fixtures

VALID_ROW = ("fac-001", "Ada Lovelace", "Psychoceramics", "0000-0002-1825-0097", "ada@example.edu")


def test_valid_seed_loads(seed_file):
    faculty = load_seed_faculty(seed_file([VALID_ROW]))

    assert len(faculty) == 1
    assert faculty[0]["faculty_id"] == "fac-001"
    assert faculty[0]["full_name"] == "Ada Lovelace"


def test_blank_orcid_is_allowed(seed_file):
    """A faculty member without an iD is harvested by name search, not rejected."""
    faculty = load_seed_faculty(seed_file([("fac-001", "Ada", "Psychoceramics", "", "a@x.edu")]))

    assert faculty[0]["orcid"] == ""


def test_surrounding_whitespace_is_stripped(seed_file):
    rows = [("  fac-001 ", " Ada Lovelace ", "Psychoceramics", "  ", "ada@example.edu")]

    faculty = load_seed_faculty(seed_file(rows))

    assert faculty[0]["faculty_id"] == "fac-001"
    assert faculty[0]["full_name"] == "Ada Lovelace"
    assert faculty[0]["orcid"] == ""


def test_multiple_rows_preserve_order(seed_file):
    rows = [VALID_ROW, ("fac-002", "Grace Hopper", "Psychoceramics", "", "g@x.edu")]

    faculty = load_seed_faculty(seed_file(rows))

    assert [record["faculty_id"] for record in faculty] == ["fac-001", "fac-002"]


def test_missing_file_is_reported(tmp_path):
    with pytest.raises(SeedDataError, match="Cannot read seed file"):
        load_seed_faculty(tmp_path / "does-not-exist.csv")


def test_empty_file_is_reported(tmp_path):
    path = tmp_path / "faculty.csv"
    path.write_text("", encoding="utf-8")

    with pytest.raises(SeedDataError, match="missing required column"):
        load_seed_faculty(path)


def test_header_without_rows_is_reported(seed_file):
    with pytest.raises(SeedDataError, match="contains no faculty rows"):
        load_seed_faculty(seed_file([]))


@pytest.mark.parametrize(
    "header",
    [
        "faculty_id,full_name",
        "full_name,department,orcid,email",
        "faculty_id,full_name,department,orcid",
        "a,b,c,d,e",
    ],
)
def test_missing_columns_are_named(tmp_path, header):
    path = tmp_path / "faculty.csv"
    path.write_text(f"{header}\nx,y\n", encoding="utf-8")

    with pytest.raises(SeedDataError, match="missing required column"):
        load_seed_faculty(path)


@pytest.mark.parametrize("column_index,column_name", [(0, "faculty_id"), (1, "full_name")])
def test_empty_required_field_is_reported(seed_file, column_index, column_name):
    row = list(VALID_ROW)
    row[column_index] = ""

    with pytest.raises(SeedDataError, match=f"empty required field '{column_name}'"):
        load_seed_faculty(seed_file([tuple(row)]))


def test_duplicate_faculty_id_is_rejected(seed_file):
    """Duplicate IDs would silently merge two people's publications in the RDF."""
    rows = [VALID_ROW, ("fac-001", "Grace Hopper", "Psychoceramics", "", "g@x.edu")]

    with pytest.raises(SeedDataError, match="duplicate faculty_id 'fac-001'"):
        load_seed_faculty(seed_file(rows))


def test_error_message_names_the_offending_line(seed_file):
    rows = [VALID_ROW, ("fac-002", "Grace", "Psychoceramics", "", "g@x.edu"), ("", "Alan", "Psychoceramics", "", "a@x.edu")]

    with pytest.raises(SeedDataError, match="line 4"):
        load_seed_faculty(seed_file(rows))


def test_invalid_utf8_is_reported(tmp_path):
    path = tmp_path / "faculty.csv"
    path.write_bytes(fixtures.SEED_HEADER.encode() + b"\n\xff\xfe,Ada,Psychoceramics,,a@x.edu\n")

    with pytest.raises(SeedDataError, match="not valid UTF-8"):
        load_seed_faculty(path)


def test_oversized_seed_list_loads(seed_file):
    """The pipeline must not assume a handful of rows."""
    rows = [(f"fac-{n:05d}", f"Person {n}", "Psychoceramics", "", f"p{n}@x.edu") for n in range(5000)]

    faculty = load_seed_faculty(seed_file(rows))

    assert len(faculty) == 5000
