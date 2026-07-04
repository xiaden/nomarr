"""ArangoDB schema migrations — versioned, repeatable database schema updates.

Migrations are discovered and applied at startup by the platform migration
runner. Each migration module defines an ``up()`` function that applies its
changes and declares a ``version`` and ``description``.
"""
