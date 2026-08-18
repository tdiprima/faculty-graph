"""Organization identity.

Written from the rule the model must uphold: one real organization gets one
node, whatever spelling or identifier form a source used to name it, and a node
must say plainly whether its identity came from a registry or from us.
"""

import pytest

from src.config import ROR_IRI_PREFIX
from src.errors import ConfigError
from src.config import normalize_ror
from src.rdf_model.organizations import (
    ORGANIZATION_KIND_LOCAL,
    ORGANIZATION_KIND_ROR,
    OrganizationRegistry,
    build_organization,
    department_organization,
    name_key,
    normalize_org_name,
    organization_from_institution,
)

EX_ROR = f"{ROR_IRI_PREFIX}abc123456"


class TestRorNormalization:
    @pytest.mark.parametrize("written", [
        "abc123456",
        "https://ror.org/abc123456",
        "http://ror.org/abc123456",
        "ror.org/abc123456",
        "  https://ror.org/abc123456/  ",
        "HTTPS://ROR.ORG/05QGHXH33",
    ])
    def test_every_written_form_collapses_to_one_iri(self, written):
        assert normalize_ror(written) == EX_ROR

    @pytest.mark.parametrize("empty", ["", "   ", None])
    def test_empty_value_is_not_an_error(self, empty):
        assert normalize_ror(empty) is None

    @pytest.mark.parametrize("bad", [
        "nope",
        "05qghxh3",
        "abc1234563",
        "https://ror.org/",
        "15qghxh33",
        "05qghxhii",
        "../../etc/passwd",
        "abc123456 OR 1=1",
    ])
    def test_malformed_identifier_is_rejected(self, bad):
        with pytest.raises(ConfigError):
            normalize_ror(bad)


class TestNameNormalization:
    @pytest.mark.parametrize("written", [
        "Example University",
        "example university",
        "The Example University",
        "  Example   University  ",
        "Example University.",
    ])
    def test_presentation_differences_share_a_key(self, written):
        assert normalize_org_name(written) == "example university"

    def test_distinct_names_do_not_collide(self):
        assert normalize_org_name("MIT") != normalize_org_name("MITRE")

    @pytest.mark.parametrize("empty", ["", "   ", None])
    def test_empty_name_has_an_empty_key(self, empty):
        assert name_key(empty) == ""

    def test_oversized_name_is_truncated_but_not_emptied(self):
        key = name_key("A" * 5000)
        assert 0 < len(key) <= 80


class TestBuildOrganization:
    def test_a_ror_identifier_becomes_the_identity(self):
        organization = build_organization("Example University", ror="abc123456")
        assert organization["ror"] == EX_ROR
        assert organization["key"] == EX_ROR
        assert organization["kind"] == ORGANIZATION_KIND_ROR

    def test_without_a_ror_the_identity_is_local(self):
        organization = build_organization("Some Institute")
        assert organization["ror"] is None
        assert organization["kind"] == ORGANIZATION_KIND_LOCAL
        assert organization["key"].startswith("name:")

    def test_a_malformed_ror_degrades_to_local_rather_than_raising(self):
        organization = build_organization("Bad Ror University", ror="not-a-ror")
        assert organization["kind"] == ORGANIZATION_KIND_LOCAL
        assert organization["ror"] is None
        assert organization["name"] == "Bad Ror University"

    @pytest.mark.parametrize("empty", ["", "   ", None])
    def test_an_organization_with_no_name_is_not_built(self, empty):
        assert build_organization(empty) is None

    def test_a_department_never_claims_a_ror(self):
        organization = department_organization("Biomedical Informatics")
        assert organization["ror"] is None
        assert organization["kind"] == ORGANIZATION_KIND_LOCAL


class TestOrganizationFromInstitution:
    def test_accepts_the_full_openalex_dict(self):
        organization = organization_from_institution({
            "display_name": "Example University",
            "ror": EX_ROR,
            "country_code": "US",
            "type": "education",
        })
        assert organization["country_code"] == "US"
        assert organization["type"] == "education"

    def test_accepts_a_bare_display_name_from_older_harvest_files(self):
        organization = organization_from_institution("Example University")
        assert organization["name"] == "Example University"
        assert organization["kind"] == ORGANIZATION_KIND_LOCAL

    @pytest.mark.parametrize("junk", [None, 42, [], {}, {"ror": EX_ROR}])
    def test_unusable_input_yields_nothing(self, junk):
        assert organization_from_institution(junk) is None


class TestRegistry:
    def test_the_same_ror_written_two_ways_registers_once(self):
        registry = OrganizationRegistry()
        registry.add(organization_from_institution(
            {"display_name": "Example University", "ror": EX_ROR}
        ))
        registry.add(organization_from_institution(
            {"display_name": "Example University", "ror": "abc123456"}
        ))
        assert len(registry) == 1

    def test_the_same_name_spelled_two_ways_registers_once(self):
        registry = OrganizationRegistry()
        registry.add(build_organization("The Example Institute"))
        registry.add(build_organization("example institute"))
        assert len(registry) == 1

    def test_a_later_record_fills_a_field_the_first_left_empty(self):
        registry = OrganizationRegistry()
        registry.add(build_organization("Example University", ror=EX_ROR))
        registry.add(build_organization(
            "Example University", ror=EX_ROR, country_code="US"
        ))
        assert registry.all()[0]["country_code"] == "US"

    def test_a_later_record_does_not_overwrite_a_known_field(self):
        registry = OrganizationRegistry()
        registry.add(build_organization("X", ror=EX_ROR, country_code="US"))
        registry.add(build_organization("X", ror=EX_ROR, country_code="CA"))
        assert registry.all()[0]["country_code"] == "US"

    def test_distinct_organizations_are_kept_apart(self):
        registry = OrganizationRegistry()
        registry.add(build_organization("Example University", ror=EX_ROR))
        registry.add(build_organization("Massachusetts Institute of Technology"))
        assert len(registry) == 2

    def test_registering_nothing_is_harmless(self):
        registry = OrganizationRegistry()
        assert registry.add(None) is None
        assert len(registry) == 0

    def test_first_seen_order_is_preserved(self):
        registry = OrganizationRegistry()
        for name in ["C", "A", "B"]:
            registry.add(build_organization(name))
        assert [o["name"] for o in registry.all()] == ["C", "A", "B"]

    def test_registry_scales_to_a_large_harvest(self):
        registry = OrganizationRegistry()
        for index in range(10000):
            registry.add(build_organization(f"Institute {index}"))
        assert len(registry) == 10000
