"""Provide real semantic tool outputs for guidance.

Contains example code and runs semantic tools on it to generate actual examples.
"""

import sys
import tempfile
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Import tools after path setup
# ruff: noqa: E402
from scripts.mcp.tools.file_symbol_at_line import file_symbol_at_line
from scripts.mcp.tools.module_discover_api import module_discover_api
from scripts.mcp.tools.module_get_source import module_get_source
from scripts.mcp.tools.module_locate_symbol import module_locate_symbol

# Example module that tools will analyze
EXAMPLE_CODE = '''"""Example for tool demonstrations."""

def calculate_sum(numbers: list[int]) -> int:
    """Sum a list of numbers."""
    return sum(numbers)

class Processor:
    """Data processor."""

    def process(self, data: str) -> dict:
        """Process data."""
        return {"result": data}

MAX_SIZE = 100
'''


def get_semantic_tool_examples() -> dict:
    """Run semantic tools on example code and return their actual outputs.

    Returns dict with tool names mapped to real example outputs.
    """
    examples = {}

    # Create temp file with example code
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(EXAMPLE_CODE)
        temp_path = Path(f.name)

    try:
        temp_dir = temp_path.parent
        module_name = temp_path.stem

        # 1. discover_api - shows module structure without reading full source
        try:
            result = module_discover_api(module_name=module_name)
            examples["discover_api"] = result
        except Exception as e:
            examples["discover_api"] = {"error": str(e)}

        # 2. locate_symbol - finds where something is defined
        try:
            result = module_locate_symbol(symbol_name="calculate_sum")
            examples["locate_symbol"] = result
        except Exception as e:
            examples["locate_symbol"] = {"error": str(e)}

        # 3. get_source - gets exact function/class with line numbers
        try:
            result = module_get_source(qualified_name=f"{module_name}.calculate_sum")
            # Truncate source for display
            if "source" in result:
                result["source"] = result["source"][:100] + "..." if len(result["source"]) > 100 else result["source"]
            examples["get_source"] = result
        except Exception as e:
            examples["get_source"] = {"error": str(e)}

        # 4. symbol_at_line - gets full context around a specific line
        try:
            result = file_symbol_at_line(file_path=str(temp_path), line_number=3, workspace_root=temp_dir)
            # Truncate source for display
            if "source" in result:
                result["source"] = result["source"][:100] + "..." if len(result["source"]) > 100 else result["source"]
            examples["symbol_at_line"] = result
        except Exception as e:
            examples["symbol_at_line"] = {"error": str(e)}

    finally:
        temp_path.unlink(missing_ok=True)

    return examples
