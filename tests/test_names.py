"""Tests for personal name handling.

Written from the rule the model must uphold: structured parts a source stated
are never merged away, and parts a source did not state are never invented.
"""

import pytest

from src.names import (
    DISPLAY,
    STRUCTURED,
    display_name_record,
    join_name,
    split_display_name,
    structured_name,
)


@pytest.mark.parametrize(
    "display,expected",
    [
        ("Ada Lovelace", ("Ada", "Lovelace")),
        ("Josiah Stinkney Carberry", ("Josiah Stinkney", "Carberry")),
        ("Lovelace, Ada", ("Ada", "Lovelace")),
        ("Ludwig van Beethoven", ("Ludwig", "van Beethoven")),
        ("Vincent van der Berg", ("Vincent", "van der Berg")),
        ("Martin Luther King Jr.", ("Martin Luther", "King")),
        ("  Ada   Lovelace  ", ("Ada", "Lovelace")),
    ],
)
def test_splits_unambiguous_display_names(display, expected):
    assert split_display_name(display) == expected


@pytest.mark.parametrize(
    "display",
    [
        "",
        "   ",
        None,
        "Prince",
        "Lovelace,",
        ",Ada",
    ],
)
def test_refuses_to_split_ambiguous_names(display):
    assert split_display_name(display) == (None, None)


def test_structured_name_keeps_parts_separate():
    record = structured_name("Ada", "Lovelace")
    assert record["given_name"] == "Ada"
    assert record["family_name"] == "Lovelace"
    assert record["name"] == "Ada Lovelace"
    assert record["name_source"] == STRUCTURED


def test_structured_name_survives_a_missing_given_name():
    record = structured_name("", "Lovelace")
    assert record["given_name"] is None
    assert record["family_name"] == "Lovelace"
    assert record["name"] == "Lovelace"


def test_display_record_flags_that_the_split_was_inferred():
    record = display_name_record("Ada Lovelace")
    assert record["name_source"] == DISPLAY
    assert record["family_name"] == "Lovelace"


def test_display_record_leaves_unsplittable_name_unsplit():
    record = display_name_record("Prince")
    assert record["name"] == "Prince"
    assert record["given_name"] is None
    assert record["family_name"] is None


def test_join_name_handles_missing_parts():
    assert join_name("Ada", "Lovelace") == "Ada Lovelace"
    assert join_name(None, "Lovelace") == "Lovelace"
    assert join_name("Ada", None) == "Ada"
    assert join_name(None, None) == ""


def test_oversized_name_is_not_truncated_by_the_splitter():
    long_family = "A" * 5000
    given, family = split_display_name(f"Ada {long_family}")
    assert given == "Ada"
    assert family == long_family
