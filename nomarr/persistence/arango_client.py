"""ArangoDB client factory for Nomarr.

Connection pooling handled automatically by python-arango client.
Thread-safe within a single process. Each process creates its own pool.
"""

from arango import ArangoClient
from arango.database import StandardDatabase


def create_arango_client(
    hosts: str = "http://nomarr-arangodb:8529",
    username: str = "nomarr",
    password: str = "nomarr_password",
    db_name: str = "nomarr",
) -> StandardDatabase:
    """Create ArangoDB client and return database handle.

    Connection pooling is handled automatically by python-arango.
    Thread-safe within a single process. Each process creates its own pool.

    Normal operation: Connects as app user to existing database.
    First-run only: May connect as root (see first_run_provision component).

    Args:
        hosts: ArangoDB server URL(s)
        username: Database username
        password: Database password
        db_name: Database name

    Returns:
        StandardDatabase instance

    Raises:
        DatabaseGetError: If database doesn't exist (signals first-run needed)
        ServerConnectionError: If cannot connect to ArangoDB service
    """
    client = ArangoClient(hosts=hosts)
    db = client.db(db_name, username=username, password=password)
    return db
