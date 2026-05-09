"""Unit tests for first-party query template assets."""

from __future__ import annotations

import pytest

from nomarr.persistence.query_specs import CapabilityFamily
from nomarr.persistence.query_templates import (
    FORBIDDEN_RAW_AQL_BIND_NAMES,
    QueryTemplateId,
    bind_first_party_query_template,
    iter_first_party_query_templates,
    template_asset,
    validate_template_bind_contract,
)


@pytest.mark.unit
class TestTemplateRegistry:
    """Tests for the closed first-party template registry."""

    def test_enumerates_every_template_id_exactly_once(self) -> None:
        """Enumeration should stay in lockstep with the fixed enum inventory."""
        assets = iter_first_party_query_templates()

        assert len(assets) == len(QueryTemplateId)
        assert {asset.template_id for asset in assets} == set(QueryTemplateId)

    def test_filters_templates_by_capability_family(self) -> None:
        """Family filtering should return only the reviewed templates for that family."""
        assets = iter_first_party_query_templates(
            capability_family=CapabilityFamily.DOCUMENT_WRITE,
        )

        assert {asset.template_id for asset in assets} == {
            QueryTemplateId.DOCUMENT_WRITE_INSERT_MANY,
            QueryTemplateId.DOCUMENT_WRITE_UPSERT_MANY,
        }

    def test_template_bind_names_never_expose_raw_aql_escape_hatches(self) -> None:
        """Reviewed template contracts must never advertise raw AQL fragments."""
        for asset in iter_first_party_query_templates():
            assert asset.bind_names().isdisjoint(FORBIDDEN_RAW_AQL_BIND_NAMES)

    def test_template_asset_accepts_fixed_string_identifier(self) -> None:
        """String lookup should resolve only reviewed template identifiers."""
        asset = template_asset("document_read.list_by_criteria")

        assert asset.template_id is QueryTemplateId.DOCUMENT_READ_LIST_BY_CRITERIA


@pytest.mark.unit
class TestTemplateBindContracts:
    """Tests for first-party bind-contract validation."""

    def test_validate_template_bind_contract_accepts_minimal_reviewed_bindings(self) -> None:
        """The contract validator should accept the required reviewed bind set."""
        validate_template_bind_contract(
            QueryTemplateId.DOCUMENT_READ_LIST_BY_CRITERIA,
            {
                "@collection": "library_files",
                "criteria": [],
                "limit": 25,
                "offset": 0,
            },
        )

    def test_validate_template_bind_contract_rejects_missing_bind_names(self) -> None:
        """Missing reviewed bind names should fail fast."""
        with pytest.raises(ValueError, match="missing limit"):
            validate_template_bind_contract(
                QueryTemplateId.DOCUMENT_READ_LIST_BY_CRITERIA,
                {
                    "@collection": "library_files",
                    "criteria": [],
                    "offset": 0,
                },
            )

    def test_validate_template_bind_contract_rejects_unexpected_bind_names(self) -> None:
        """Unexpected bind names should not be silently tolerated."""
        with pytest.raises(ValueError, match="Unexpected bind variables"):
            validate_template_bind_contract(
                QueryTemplateId.DOCUMENT_READ_LIST_BY_CRITERIA,
                {
                    "@collection": "library_files",
                    "criteria": [],
                    "limit": 25,
                    "offset": 0,
                    "unexpected": True,
                },
            )

    def test_validate_template_bind_contract_rejects_raw_aql_fragments(self) -> None:
        """Raw-AQL bind names should be rejected at the template layer."""
        with pytest.raises(ValueError, match="Raw AQL fragments are not allowed"):
            validate_template_bind_contract(
                QueryTemplateId.DOCUMENT_READ_LIST_BY_CRITERIA,
                {
                    "@collection": "library_files",
                    "criteria": [],
                    "limit": 25,
                    "offset": 0,
                    "raw_aql": "FOR doc IN library_files RETURN doc",
                },
            )

    def test_bind_first_party_query_template_returns_bound_asset_snapshot(self) -> None:
        """Binding should preserve the fixed template identifier and reviewed bind vars."""
        bound = bind_first_party_query_template(
            QueryTemplateId.DOCUMENT_READ_LIST_BY_CRITERIA,
            {
                "@collection": "library_files",
                "criteria": [],
                "limit": 10,
                "offset": 0,
            },
        )

        assert bound.template_id is QueryTemplateId.DOCUMENT_READ_LIST_BY_CRITERIA
        assert bound.bind_vars["@collection"] == "library_files"
        assert bound.bind_vars["limit"] == 10
