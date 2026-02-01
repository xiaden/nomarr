"""Classification logic and suspect import detection."""

from .config import is_ignored_module
from .model import DataclassInfo, ImportEdge


def detect_suspect_imports(
    import_edges: list[ImportEdge], allowed_imports: list[list[str]], ignore_prefixes: list[str],
) -> list[ImportEdge]:
    """Detect suspect imports based on allowed_imports configuration.

    This is for reporting only, not enforcement.

    Args:
        import_edges: List of all import edges found
        allowed_imports: List of [from_layer, to_layer] allowed pairs
        ignore_prefixes: List of module prefixes to ignore

    Returns:
        List of ImportEdge objects that are not in allowed_imports (excluding ignored modules)

    """
    if not allowed_imports:
        return []

    # Convert allowed_imports to a set of tuples for faster lookup
    allowed_set = {(from_layer, to_layer) for from_layer, to_layer in allowed_imports}

    suspect: list[ImportEdge] = []
    seen = set()

    for edge in import_edges:
        # Skip edges involving ignored modules
        if is_ignored_module(edge.importer_module, ignore_prefixes) or is_ignored_module(
            edge.imported_module, ignore_prefixes,
        ):
            continue

        # Create a unique key for deduplication
        edge_key = (edge.importer_module, edge.imported_module)
        if edge_key in seen:
            continue
        seen.add(edge_key)

        # Check if this edge is allowed
        if (edge.importer_layer, edge.imported_layer) not in allowed_set:
            suspect.append(edge)

    return suspect


def infer_domain_from_dataclass(dc: DataclassInfo) -> str:
    """Infer domain from DataclassInfo, preferring defining_domain but falling back to imported_by_domains.

    Args:
        dc: DataclassInfo object

    Returns:
        Domain name (may be "unknown")

    """
    if dc.defining_domain != "unknown":
        return dc.defining_domain

    # If defining domain is unknown, try to infer from importers
    domains = dc.imported_by_domains - {"unknown"}
    if len(domains) == 1:
        return domains.pop()

    return "unknown"


def classify_dataclass(dc: DataclassInfo) -> None:
    """Classify a dataclass and suggest target location (mutates DataclassInfo).

    Args:
        dc: DataclassInfo object to classify

    """
    # If dataclass is defined in an ignored module, classify as "Ignored"
    if dc.is_ignored:
        dc.classification = "Ignored"
        dc.suggested_target = "n/a"
        dc.notes = "Defined in an ignored module; excluded from architectural analysis."
        return

    module = dc.defining_module
    packages = dc.imported_by_packages
    num_packages = len(packages)
    num_modules = len(dc.imported_by_modules)

    # E) Persistence Model
    if module.startswith("nomarr.persistence"):
        dc.classification = "Persistence Model"
        dc.suggested_target = f"{module} (keep in place)"
        dc.notes = "Database/queue structure; belongs in persistence layer."
        return

    # Check if in helpers/dto/
    if module.startswith("nomarr.helpers.dto."):
        if num_packages >= 2:
            dc.classification = "Cross-Layer DTO"
            dc.suggested_target = f"{module} (already correct)"
            dc.notes = f"Imported by {num_packages} packages: {', '.join(sorted(packages))}"
        else:
            dc.classification = "Domain-Internal Helper"
            domain = infer_domain_from_dataclass(dc)
            dc.suggested_target = f"helpers/dto/{domain}.py (may be misplaced if only used internally)"
            dc.notes = "In DTO module but only used by one package; verify it's truly cross-layer."
        return

    # Check if in helpers/ (but not dto/)
    if module.startswith("nomarr.helpers"):
        if num_packages >= 2:
            dc.classification = "Cross-Domain Helper"
            dc.suggested_target = "helpers/dataclasses.py"
            dc.notes = f"Imported by {num_packages} packages: {', '.join(sorted(packages))}"
        else:
            dc.classification = "Domain-Internal Helper"
            domain = infer_domain_from_dataclass(dc)
            dc.suggested_target = f"workflows/{domain}/types.py or components/{domain}/types.py"
            dc.notes = "In helpers/ but only used by one domain; may be misplaced."
        return

    # Check if in services/
    if module.startswith("nomarr.services"):
        if num_modules == 0:
            # Not imported anywhere else
            dc.classification = "Service-Local Config"
            dc.suggested_target = f"{module} (keep in place)"
            dc.notes = "Only used within defining service module."
        elif packages <= {"services"}:
            # Only imported by other services
            dc.classification = "Service-Local Config"
            dc.suggested_target = f"{module} (keep in place)"
            dc.notes = "Only used by service modules."
        else:
            # Imported by workflows/components/interfaces
            dc.classification = "Cross-Layer DTO"
            domain = infer_domain_from_dataclass(dc)
            dc.suggested_target = f"helpers/dto/{domain}.py"
            dc.notes = f"Currently in services/ but imported by: {', '.join(sorted(packages))}. Should move to DTO."
        return

    # Check if in workflows/
    if module.startswith("nomarr.workflows"):
        if num_modules == 0:
            dc.classification = "Workflow-Local Helper"
            dc.suggested_target = f"{module} (keep in place)"
            dc.notes = "Only used within defining workflow file."
        elif all(m.startswith(module.rsplit(".", 1)[0]) for m in dc.imported_by_modules):
            # Only imported within same workflow domain
            dc.classification = "Domain-Internal Helper"
            domain = infer_domain_from_dataclass(dc)
            dc.suggested_target = f"workflows/{domain}/types.py"
            dc.notes = f"Used across {num_modules} modules in same domain."
        elif num_packages >= 2:
            dc.classification = "Cross-Layer DTO"
            domain = infer_domain_from_dataclass(dc)
            dc.suggested_target = f"helpers/dto/{domain}.py"
            dc.notes = f"Currently in workflows/ but imported by: {', '.join(sorted(packages))}. Should move to DTO."
        else:
            dc.classification = "Domain-Internal Helper"
            domain = infer_domain_from_dataclass(dc)
            dc.suggested_target = f"workflows/{domain}/types.py"
            dc.notes = "Used by multiple modules in one domain."
        return

    # Check if in components/
    if module.startswith("nomarr.components"):
        if num_packages >= 2 and (packages & {"services", "workflows", "interfaces"}):
            dc.classification = "Cross-Layer DTO"
            domain = infer_domain_from_dataclass(dc)
            dc.suggested_target = f"helpers/dto/{domain}.py"
            dc.notes = f"Currently in components/ but imported by: {', '.join(sorted(packages))}. Should move to DTO."
        else:
            dc.classification = "Domain-Internal Helper"
            domain = infer_domain_from_dataclass(dc)
            dc.suggested_target = f"components/{domain}/types.py"
            dc.notes = "Only used within component domain."
        return

    # G) Ambiguous - couldn't classify
    dc.classification = "Ambiguous"
    dc.suggested_target = "manual review required"
    dc.notes = f"Defined in {module}, imported by {num_packages} packages. Needs manual classification."


def classify_all(dataclasses: list[DataclassInfo]) -> None:
    """Classify all dataclasses (mutates DataclassInfo objects).

    Args:
        dataclasses: List of DataclassInfo objects to classify

    """
    for dc in dataclasses:
        classify_dataclass(dc)
