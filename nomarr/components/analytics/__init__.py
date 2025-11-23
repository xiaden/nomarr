"""
Analytics package - tag statistics, correlations, and co-occurrences.

This is a PURE COMPUTATION leaf-domain package similar to nomarr.ml and nomarr.tagging.
It provides analytics functions that operate on in-memory data (NOT databases).

Architecture:
- Analytics is a pure computation layer - takes raw data, returns results
- Analytics must NOT import persistence, services, workflows, or interfaces
- Analytics may ONLY import helpers and stdlib (json, logging, collections, typing)
- Data is provided by persistence layer (nomarr.persistence.analytics_queries)
- Services orchestrate: persistence (fetch data) → analytics (compute) → results

For usage, see nomarr.services.analytics.AnalyticsService which orchestrates
between persistence and analytics layers.
"""
