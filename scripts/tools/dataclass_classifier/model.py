"""
Data models for the dataclass classifier toolkit.
"""

from pathlib import Path
from typing import Any


class DataclassInfo:
    """Information about a discovered dataclass."""

    def __init__(
        self,
        name: str,
        defining_module: str,
        defining_file: Path,
        defining_layer: str,
        defining_domain: str,
        is_ignored: bool,
    ):
        self.name = name
        self.defining_module = defining_module
        self.defining_file = defining_file
        self.defining_layer = defining_layer
        self.defining_domain = defining_domain
        self.is_ignored = is_ignored
        # For backward compatibility with existing code
        self.top_level_package = self.defining_layer
        self.imported_by_modules: list[str] = []
        self.imported_by_packages: set[str] = set()
        self.imported_by_layers: set[str] = set()
        self.imported_by_domains: set[str] = set()
        self.ignored_import_count: int = 0
        self.classification: str = "Unknown"
        self.suggested_target: str = ""
        self.notes: str = ""

    def to_dict(self, project_root: Path) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "defining_module": self.defining_module,
            "defining_file": str(self.defining_file.relative_to(project_root)),
            "defining_layer": self.defining_layer,
            "defining_domain": self.defining_domain,
            "top_level_package": self.top_level_package,
            "imported_by_modules": sorted(self.imported_by_modules),
            "imported_by_packages": sorted(self.imported_by_packages),
            "imported_by_layers": sorted(self.imported_by_layers),
            "imported_by_domains": sorted(self.imported_by_domains),
            "classification": self.classification,
            "suggested_target": self.suggested_target,
            "notes": self.notes,
        }


class ImportEdge:
    """Represents an import edge between two modules."""

    def __init__(
        self,
        importer_module: str,
        imported_module: str,
        importer_layer: str,
        imported_layer: str,
    ):
        self.importer_module = importer_module
        self.imported_module = imported_module
        self.importer_layer = importer_layer
        self.imported_layer = imported_layer

    def to_dict(self) -> dict[str, str]:
        """Convert to dictionary for JSON serialization."""
        return {
            "importer_module": self.importer_module,
            "importer_layer": self.importer_layer,
            "imported_module": self.imported_module,
            "imported_layer": self.imported_layer,
        }


class MissingDataclassCandidate:
    """Information about a function that might benefit from a dataclass/DTO."""

    def __init__(
        self,
        module: str,
        function: str,
        defining_file: Path,
        layer: str,
        domain: str,
        reason: str,
        fields: list[str],
        suggested_name: str,
        is_private: bool = False,
    ):
        self.module = module
        self.function = function
        self.defining_file = defining_file
        self.layer = layer
        self.domain = domain
        self.reason = reason
        self.fields = fields
        self.suggested_name = suggested_name
        self.is_private = is_private

    def to_dict(self, project_root: Path) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "module": self.module,
            "function": self.function,
            "defining_file": str(self.defining_file.relative_to(project_root)),
            "layer": self.layer,
            "domain": self.domain,
            "reason": self.reason,
            "fields": self.fields,
            "suggested_name": self.suggested_name,
            "is_private": self.is_private,
        }
