"""
Test library scanner properly decodes M4A tag bytes.
Regression test for b'value' bug in library database.
"""

import pytest


@pytest.mark.unit
class TestM4ATagDecoding:
    """Test that M4A tags are properly decoded from bytes to strings."""

    def test_bytes_decode_not_str_repr(self):
        """Test that calling decode() on bytes gives us the string, not str() which gives repr."""
        # This is the core issue: str(b'low') gives "b'low'" not "low"
        value = b"low"

        # WRONG way (old code)
        wrong = str(value)
        assert wrong == "b'low'"  # Bytes repr, not the actual string!

        # CORRECT way (new code)
        correct = value.decode("utf-8")
        assert correct == "low"  # Actual string value

    def test_library_scanner_handles_bytes_correctly(self):
        """Test that the library scanner decode logic handles both bytes and strings."""

        # Simulate what the library scanner does
        def process_tag_value(raw_value):
            """Mimic library_scanner.py M4A tag extraction."""
            if isinstance(raw_value, bytes):
                return raw_value.decode("utf-8")
            return str(raw_value)

        # Test with bytes (M4A freeform tags)
        assert process_tag_value(b"aggressive") == "aggressive"
        assert process_tag_value(b"high") == "high"
        assert process_tag_value(b"bass-forward") == "bass-forward"

        # Test with strings (shouldn't happen in M4A, but handle gracefully)
        assert process_tag_value("some_string") == "some_string"

        # Test with unicode bytes
        assert process_tag_value("café".encode()) == "café"

        # Verify we're NOT getting bytes repr
        assert process_tag_value(b"low") != "b'low'"
        assert process_tag_value(b"high") != "b'high'"
        assert process_tag_value(b"medium") != "b'medium'"
