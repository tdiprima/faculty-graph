"""Resolve query templates against the configured institution.

A .rq file is static text, so SPARQL cannot read configuration for itself.
Templates under queries/ carry named placeholders, and this module substitutes
the configured values at the moment a query is used.

Substitution is deliberately narrow: only known placeholder names are replaced,
and the result is checked for leftovers. A query that silently kept an
unsubstituted placeholder would run and return nothing, which is the worst
failure mode available — no error, no results, no reason.
"""

import logging
import re
from pathlib import Path

from src.config import base_uri, institution_name, institution_rors, project_root
from src.errors import ConfigError

logger = logging.getLogger(__name__)

QUERIES_DIRNAME = "queries"
QUERY_SUFFIX = ".rq"

PLACEHOLDER_PATTERN = re.compile(r"\{\{([A-Z_]+)\}\}")

# A SPARQL VALUES clause takes a whitespace-separated list of IRIs, so several
# home institutions need no query change — only a longer substitution.
VALUES_INDENT = "        "


def queries_dir():
    """Directory holding the query templates."""
    return project_root() / QUERIES_DIRNAME


def available_queries():
    """Return the names of every shipped query, without the .rq suffix."""
    return sorted(path.stem for path in queries_dir().glob(f"*{QUERY_SUFFIX}"))


def _format_iri_list(iris):
    """Render IRIs for a VALUES clause, one per line when there are several."""
    if not iris:
        return ""
    if len(iris) == 1:
        return f"<{iris[0]}>"
    return f"\n{VALUES_INDENT}".join(f"<{iri}>" for iri in iris)


def build_substitutions():
    """Return the placeholder values for the current configuration."""
    home_rors = institution_rors()
    return {
        "FG_BASE_URI": base_uri(),
        "FGDATA_BASE_URI": f"{base_uri()}data/",
        "INSTITUTION_NAME": institution_name(),
        "INSTITUTION_ROR_VALUES": _format_iri_list(home_rors),
    }


def resolve_query(template, substitutions=None):
    """Substitute placeholders in one query template.

    Raises ConfigError when a placeholder has no value, rather than emitting a
    query that would run and quietly match nothing.
    """
    substitutions = substitutions or build_substitutions()

    def replace(match):
        name = match.group(1)
        if name not in substitutions:
            raise ConfigError(
                f"Query uses unknown placeholder {{{{{name}}}}}. "
                f"Known placeholders: {', '.join(sorted(substitutions))}"
            )
        value = substitutions[name]
        if not value:
            raise ConfigError(
                f"Query needs {{{{{name}}}}} but it resolves to nothing. "
                f"Set the matching variable in .env (see .env.example)."
            )
        return value

    resolved = PLACEHOLDER_PATTERN.sub(replace, template)

    leftover = PLACEHOLDER_PATTERN.findall(resolved)
    if leftover:
        raise ConfigError(f"Query still contains placeholders after substitution: {leftover}")

    return resolved


def load_query(name, substitutions=None):
    """Read one query template by name and resolve it."""
    safe_name = Path(name).name
    if safe_name != name or not safe_name:
        raise ConfigError(f"Not a valid query name: {name!r}")

    path = queries_dir() / f"{safe_name}{QUERY_SUFFIX}"
    if not path.exists():
        raise ConfigError(
            f"No such query: {safe_name}. Available: {', '.join(available_queries())}"
        )

    return resolve_query(path.read_text(encoding="utf-8"), substitutions)


def write_resolved_queries(output_dir):
    """Write every query, resolved, into output_dir. Returns the paths written.

    Useful for pasting into a SPARQL GUI or running with curl, where a file that
    needs no further editing is the point.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    substitutions = build_substitutions()
    written = []

    for name in available_queries():
        path = output_dir / f"{name}{QUERY_SUFFIX}"
        path.write_text(load_query(name, substitutions), encoding="utf-8")
        written.append(path)

    logger.info("Wrote %d resolved queries to %s", len(written), output_dir)
    return written
