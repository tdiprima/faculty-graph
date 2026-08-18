"""Institution configuration is read from the environment and validated."""

import pytest

from src import config
from src.errors import ConfigError


def test_institution_name_defaults_to_the_placeholder(monkeypatch):
    monkeypatch.delenv("INSTITUTION_NAME", raising=False)

    assert config.institution_name() == config.DEFAULT_INSTITUTION_NAME


def test_institution_name_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("INSTITUTION_NAME", "  Example University  ")

    assert config.institution_name() == "Example University"


def test_empty_institution_name_is_allowed(monkeypatch):
    """An empty name means 'do not constrain by institution', not an error."""
    monkeypatch.setenv("INSTITUTION_NAME", "   ")

    assert config.institution_name() == ""


def test_affiliation_falls_back_to_the_institution_name(monkeypatch):
    monkeypatch.setenv("INSTITUTION_NAME", "Example University")
    monkeypatch.delenv("INSTITUTION_AFFILIATION", raising=False)

    assert config.institution_affiliation() == "Example University"


def test_affiliation_overrides_the_institution_name(monkeypatch):
    monkeypatch.setenv("INSTITUTION_NAME", "Example University")
    monkeypatch.setenv("INSTITUTION_AFFILIATION", "Example U")

    assert config.institution_affiliation() == "Example U"


def test_base_uri_defaults(monkeypatch):
    monkeypatch.delenv("FG_BASE_URI", raising=False)

    assert config.base_uri() == config.DEFAULT_BASE_URI


def test_base_uri_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("FG_BASE_URI", "https://data.example.edu/fg/")

    assert config.base_uri() == "https://data.example.edu/fg/"


@pytest.mark.parametrize(
    "value",
    [
        "data.example.edu/fg/",          # no scheme
        "ftp://data.example.edu/fg/",    # wrong scheme
        "https://data.example.edu/fg",   # missing trailing slash
    ],
)
def test_malformed_base_uri_is_rejected(monkeypatch, value):
    """A bad base would produce Turtle that no triple store can load."""
    monkeypatch.setenv("FG_BASE_URI", value)

    with pytest.raises(ConfigError):
        config.base_uri()
