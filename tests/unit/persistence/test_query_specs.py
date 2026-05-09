"""Unit tests for collection-first query-spec metadata contracts."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.persistence.collections import LibraryFiles
from nomarr.persistence.query_specs import (
    CapabilityFamily,
    CollectionFamily,
    QueryOperator,
    allowed_public_roots,
    capability_metadata,
    collection_metadata_from_provider,
    is_allowed_public_capability_root,
    is_collection_family_supported,
    is_operator_name,
    is_storage_native_capability_family,
    supported_collection_families,
    supported_operators,
)


class _ProviderStub:
    """Minimal metadata provider for query-spec tests."""

    def __init__(self, metadata: dict[str, object]) -> None:
        self._metadata = metadata

    def _query_collection_metadata(self) -> dict[str, object]:
        return self._metadata


@pytest.mark.unit
@pytest.mark.mocked
class TestCapabilityMetadata:
    """Tests for capability-family metadata and naming grammar."""

    def test_document_read_metadata_is_generic_and_collection_first(self) -> None:
        """Document-read metadata should stay generic and operator-driven."""
        metadata = capability_metadata(CapabilityFamily.DOCUMENT_READ)

        assert metadata.storage_native is False
        assert CollectionFamily.DOCUMENT in metadata.allowed_collection_families
        assert supported_operators(CapabilityFamily.DOCUMENT_READ) == frozenset(
            {
                QueryOperator.EQ,
                QueryOperator.GTE,
                QueryOperator.IN,
                QueryOperator.LIKE,
                QueryOperator.LTE,
            },
        )

    def test_ann_search_metadata_is_storage_native_and_operator_limited(self) -> None:
        """ANN search should remain a storage-native special capability."""
        metadata = capability_metadata(CapabilityFamily.ANN_SEARCH)

        assert metadata.storage_native is True
        assert metadata.allowed_collection_families == frozenset({CollectionFamily.VECTOR})
        assert supported_operators(CapabilityFamily.ANN_SEARCH) == frozenset(
            {QueryOperator.EQ, QueryOperator.IN},
        )

    def test_naming_grammar_allows_normalized_roots_but_reserves_operator_names(self) -> None:
        """Public capability roots should stay closed and not overlap operators."""
        assert is_allowed_public_capability_root("read", CapabilityFamily.DOCUMENT_READ) is True
        assert is_allowed_public_capability_root("search", CapabilityFamily.DOCUMENT_READ) is False
        assert is_operator_name("eq") is True
        assert is_allowed_public_capability_root("eq", CapabilityFamily.DOCUMENT_READ) is False


@pytest.mark.unit
@pytest.mark.mocked
class TestCapabilityHelpers:
    """Tests for capability-family helper accessors."""

    def test_supported_collection_families_returns_frozenset(self) -> None:
        """Document reads should expose a frozenset of supported collection families."""
        families = supported_collection_families(CapabilityFamily.DOCUMENT_READ)

        assert isinstance(families, frozenset)
        assert CollectionFamily.DOCUMENT in families

    def test_is_collection_family_supported_true_for_document_read(self) -> None:
        """Document collections should be supported for document-read capabilities."""
        assert (
            is_collection_family_supported(
                CapabilityFamily.DOCUMENT_READ,
                CollectionFamily.DOCUMENT,
            )
            is True
        )

    def test_is_storage_native_returns_true_for_ann(self) -> None:
        """Only storage-native capability families should report ``True``."""
        assert is_storage_native_capability_family(CapabilityFamily.ANN_SEARCH) is True
        assert is_storage_native_capability_family(CapabilityFamily.DOCUMENT_READ) is False

    def test_allowed_public_roots_returns_frozenset_for_document_read(self) -> None:
        """Public roots should be returned as a non-empty frozenset."""
        roots = allowed_public_roots(CapabilityFamily.DOCUMENT_READ)

        assert isinstance(roots, frozenset)
        assert roots


@pytest.mark.unit
@pytest.mark.mocked
class TestCollectionMetadataFromProvider:
    """Tests for metadata extraction from persistence providers."""

    def test_extracts_collection_and_unique_field_metadata_from_real_collection(self) -> None:
        """Real collection wrappers should expose minimal query metadata."""
        metadata = collection_metadata_from_provider(LibraryFiles(MagicMock()))

        assert metadata.collection_name == "library_files"
        assert metadata.collection_family is CollectionFamily.DOCUMENT
        assert metadata.fields["path"].name == "path"
        assert metadata.fields["path"].unique is True
        assert metadata.fields["artist"].unique is False

    def test_rejects_non_mapping_fields_metadata(self) -> None:
        """The provider contract should reject malformed field registries."""
        provider = _ProviderStub(
            {
                "collection_name": "broken",
                "collection_family": CollectionFamily.DOCUMENT.value,
                "fields": ["not", "a", "mapping"],
            },
        )

        with pytest.raises(TypeError, match="fields metadata must be a mapping"):
            collection_metadata_from_provider(provider)

    def test_rejects_non_mapping_field_entries(self) -> None:
        """Each field entry should be a metadata mapping, not arbitrary data."""
        provider = _ProviderStub(
            {
                "collection_name": "broken",
                "collection_family": CollectionFamily.DOCUMENT.value,
                "fields": {"path": "not-a-mapping"},
            },
        )

        with pytest.raises(TypeError, match="field metadata entries must be mappings"):
            collection_metadata_from_provider(provider)
