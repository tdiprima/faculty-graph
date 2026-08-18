"""Query templates resolve against configuration, and fail loudly when they cannot.

The failure this guards against is specific: a query that keeps an unsubstituted
placeholder still parses as SPARQL, runs against the endpoint, and returns
nothing. No error, no results, no reason. Every test here exists to make that
outcome impossible.
"""

import pytest

from src.config import institution_ror, institution_rors, load_env_file, normalize_ror
from src.errors import ConfigError
from src.queries import (
    available_queries,
    build_substitutions,
    load_query,
    resolve_query,
    write_resolved_queries,
)

EX_ROR = "https://ror.org/abc123456"
EX_HOSPITAL_ROR = "https://ror.org/abc123456"


@pytest.fixture
def configured(monkeypatch):
    """A single configured home institution."""
    monkeypatch.setenv("INSTITUTION_ROR", EX_ROR)
    monkeypatch.setenv("INSTITUTION_NAME", "Example University")
    monkeypatch.delenv("FG_BASE_URI", raising=False)


class TestMultipleHomeRors:
    def test_a_single_ror_is_read(self, monkeypatch):
        monkeypatch.setenv("INSTITUTION_ROR", EX_ROR)
        assert institution_rors() == [EX_ROR]

    def test_several_rors_are_read_in_order(self, monkeypatch):
        monkeypatch.setenv("INSTITUTION_ROR", f"{EX_ROR},{EX_HOSPITAL_ROR}")
        assert institution_rors() == [EX_ROR, EX_HOSPITAL_ROR]

    def test_mixed_written_forms_are_all_normalized(self, monkeypatch):
        monkeypatch.setenv("INSTITUTION_ROR", "abc123456, http://ror.org/abc123456")
        assert institution_rors() == [EX_ROR, EX_HOSPITAL_ROR]

    def test_surrounding_whitespace_is_ignored(self, monkeypatch):
        monkeypatch.setenv("INSTITUTION_ROR", f"  {EX_ROR} ,  {EX_HOSPITAL_ROR}  ")
        assert institution_rors() == [EX_ROR, EX_HOSPITAL_ROR]

    def test_a_repeated_ror_is_listed_once(self, monkeypatch):
        monkeypatch.setenv("INSTITUTION_ROR", f"{EX_ROR},abc123456")
        assert institution_rors() == [EX_ROR]

    @pytest.mark.parametrize("empty", ["", "   ", ",", " , , "])
    def test_an_empty_setting_yields_no_home_institution(self, monkeypatch, empty):
        monkeypatch.setenv("INSTITUTION_ROR", empty)
        assert institution_rors() == []
        assert institution_ror() is None

    def test_the_primary_ror_is_the_first_configured(self, monkeypatch):
        monkeypatch.setenv("INSTITUTION_ROR", f"{EX_HOSPITAL_ROR},{EX_ROR}")
        assert institution_ror() == EX_HOSPITAL_ROR

    def test_one_malformed_entry_fails_the_whole_setting(self, monkeypatch):
        monkeypatch.setenv("INSTITUTION_ROR", f"{EX_ROR},not-a-ror")
        with pytest.raises(ConfigError):
            institution_rors()


class TestResolution:
    def test_every_shipped_query_resolves(self, configured):
        for name in available_queries():
            assert "{{" not in load_query(name)

    def test_the_configured_ror_reaches_the_query(self, configured):
        assert EX_ROR in load_query("collaborating-institutions")

    def test_several_home_rors_all_reach_the_query(self, monkeypatch):
        monkeypatch.setenv("INSTITUTION_ROR", f"{EX_ROR},{EX_HOSPITAL_ROR}")
        query = load_query("collaborating-institutions")
        assert EX_ROR in query
        assert EX_HOSPITAL_ROR in query

    def test_the_configured_base_iri_reaches_the_query(self, monkeypatch, configured):
        monkeypatch.setenv("FG_BASE_URI", "https://graph.example.edu/fg/")
        query = load_query("collaborating-institutions")
        assert "PREFIX fg:     <https://graph.example.edu/fg/>" in query
        assert "example.org" not in query

    def test_no_shipped_template_hardcodes_one_institution(self):
        from src.queries import queries_dir

        for path in queries_dir().glob("*.rq"):
            body = "\n".join(
                line for line in path.read_text(encoding="utf-8").splitlines()
                if not line.strip().startswith("#")
            )
            assert EX_ROR not in body, f"{path.name} hardcodes our own ROR"


class TestFailsLoudly:
    def test_an_unset_ror_is_an_error_not_an_empty_query(self, monkeypatch):
        monkeypatch.setenv("INSTITUTION_ROR", "")
        with pytest.raises(ConfigError, match="INSTITUTION_ROR_VALUES"):
            load_query("collaborating-institutions")

    def test_an_unknown_placeholder_is_rejected(self):
        with pytest.raises(ConfigError, match="unknown placeholder"):
            resolve_query("SELECT * WHERE { {{NO_SUCH_THING}} }", {"FG_BASE_URI": "x"})

    def test_an_unknown_query_name_lists_what_exists(self, configured):
        with pytest.raises(ConfigError, match="No such query"):
            load_query("no-such-query")

    @pytest.mark.parametrize("hostile", [
        "../src/config",
        "../../etc/passwd",
        "/etc/passwd",
        "",
        "sub/dir/query",
    ])
    def test_a_traversing_query_name_is_refused(self, configured, hostile):
        with pytest.raises(ConfigError):
            load_query(hostile)

    def test_a_resolved_query_never_keeps_a_placeholder(self, configured):
        substitutions = build_substitutions()
        for name in available_queries():
            assert "{{" not in load_query(name, substitutions)


class TestEnvFile:
    def test_a_missing_env_file_is_not_an_error(self, tmp_path):
        assert load_env_file(tmp_path / "absent.env") is None

    def test_values_are_read_from_the_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("INSTITUTION_ROR", raising=False)
        env = tmp_path / ".env"
        env.write_text(f'INSTITUTION_ROR="{EX_ROR}"\n', encoding="utf-8")
        load_env_file(env)
        assert institution_rors() == [EX_ROR]

    def test_an_exported_variable_beats_the_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("INSTITUTION_ROR", EX_HOSPITAL_ROR)
        env = tmp_path / ".env"
        env.write_text(f'INSTITUTION_ROR="{EX_ROR}"\n', encoding="utf-8")
        load_env_file(env)
        assert institution_rors() == [EX_HOSPITAL_ROR]

    def test_the_shipped_example_is_readable_and_valid(self, tmp_path, monkeypatch):
        import shutil

        from src.config import project_root

        monkeypatch.delenv("INSTITUTION_ROR", raising=False)
        monkeypatch.delenv("INSTITUTION_NAME", raising=False)

        env = tmp_path / ".env"
        shutil.copy(project_root() / ".env.example", env)
        load_env_file(env)

        assert institution_rors() == [EX_ROR, EX_HOSPITAL_ROR]
        assert normalize_ror(institution_ror()) == EX_ROR


class TestWriteResolvedQueries:
    def test_writes_every_query(self, tmp_path, configured):
        written = write_resolved_queries(tmp_path)
        assert len(written) == len(available_queries())
        for path in written:
            assert "{{" not in path.read_text(encoding="utf-8")

    def test_written_queries_are_runnable_sparql(self, tmp_path, configured):
        rdflib = pytest.importorskip("rdflib")
        for path in write_resolved_queries(tmp_path):
            rdflib.Graph().query(path.read_text(encoding="utf-8"))
