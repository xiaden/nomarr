"""Metadata components — compute-only metadata derivation helpers.

Holds helpers that derive metadata purely from raw audio tags: entity-tag
mapping derivation (:mod:`entity_seeding_comp`) and forward-compatible
metadata-cache field computation (:mod:`metadata_cache_comp`).  No DB writes
happen here; the obsolete DB write path was removed per ADR-045.
"""
