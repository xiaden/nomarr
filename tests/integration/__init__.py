"""
Integration tests for nomarr production system.

These tests verify the actual production system works end-to-end:
- Real API endpoints (not mocked)
- Real ML models and inference
- Real audio file processing
- Real database operations

Designed to run in Docker container to catch production image issues.
"""
