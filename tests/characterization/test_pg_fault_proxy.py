"""Control and negative tests for the D3D-A PostgreSQL fault proxy.

These tests prove the *harness* is trustworthy before D3D-B relies on it. The
suite has 14 tests (5 live-PostgreSQL, 9 socket-only):

Live-PostgreSQL (``requires_database``):
1. normal proxy control (transparent pass-through, commits persist)
2. concurrent connections isolate faults (one-shot is per-connection)
3. one-shot arming faults only the next commit
4. ``DROP_ACK`` control (pgcode-less ``DBAPIError``; exact
   ``psycopg2.OperationalError`` driver class; server did commit)
5. ``SEVER`` control (pgcode-less connection-closed ``DBAPIError``; exact
   ``psycopg2.OperationalError`` driver class; no leaks)

Socket-only (no live PostgreSQL):
6. credential redaction never renders the password
7. stop/disarm are idempotent and leak-free
8. malformed frontend frame -> typed :class:`FaultHarnessError`
9. unavailable backend -> typed :class:`HarnessInfrastructureError`
10. forced harness timeout -> typed :class:`HarnessTimeoutError`
11. Round-2 DROP_ACK commit-validation guard: ReadyForQuery without a prior
    COMMIT ``CommandComplete``
    (``test_drop_ack_ready_without_commit_command_complete_is_rejected``)
12. Round-2 DROP_ACK commit-validation guard: ReadyForQuery with non-idle status
    (``test_drop_ack_non_idle_ready_for_query_is_rejected``)
13. Round-2 partial-frame relay-desync guard, client side
    (``test_mid_frame_client_side_desync_is_infrastructure_error``)
14. Round-2 partial-frame relay-desync guard, backend side
    (``test_mid_frame_backend_side_desync_is_infrastructure_error``)

Only tests that use a live PostgreSQL server are marked ``requires_database``.
"""

from __future__ import annotations

import contextlib
import socket
import struct
import threading
import uuid
from typing import TYPE_CHECKING

import psycopg2
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from nomarr.persistence.db import Database

from .pg_fault_proxy import (
    FaultHarnessError,
    HarnessInfrastructureError,
    HarnessTimeoutError,
    PgFaultMode,
    PgFaultProxy,
    redact_url,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine

pytestmark = pytest.mark.characterization

_ACCEPT_TIMEOUT = 0.2
_STARTUP_PROTOCOL_VERSION = 196608


def _open_db(url: str) -> Database:
    return Database(url=url, echo=False, pool_size=1, max_overflow=0)


def _pgcode(exc: DBAPIError) -> str | None:
    return getattr(getattr(exc, "orig", None), "pgcode", None)


def _orig_error(exc: DBAPIError) -> BaseException | None:
    return getattr(exc, "orig", None)


def _unique_table() -> str:
    return f"d3da_proxy_probe_{uuid.uuid4().hex[:12]}"


def _dummy_url(port: int) -> str:
    return f"postgresql+psycopg2://nomarr:nomarr@127.0.0.1:{port}/postgres"


def _startup_message() -> bytes:
    params = b"user\x00nomarr\x00database\x00postgres\x00\x00"
    payload = struct.pack(">I", _STARTUP_PROTOCOL_VERSION) + params
    return struct.pack(">I", 4 + len(payload)) + payload


def _query_message(sql: str) -> bytes:
    payload = sql.encode("ascii") + b"\x00"
    return b"Q" + struct.pack(">I", 4 + len(payload)) + payload


def _unused_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
    finally:
        probe.close()


@contextlib.contextmanager
def _silent_backend() -> Iterator[int]:
    """A TCP backend that accepts connections and never sends bytes."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    listener.settimeout(_ACCEPT_TIMEOUT)
    port = int(listener.getsockname()[1])
    stop = threading.Event()
    held: list[socket.socket] = []

    def serve() -> None:
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            held.append(conn)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        stop.set()
        with contextlib.suppress(OSError):
            listener.close()
        for conn in held:
            with contextlib.suppress(OSError):
                conn.close()
        thread.join(timeout=2.0)


# --------------------------------------------------------------------------
# Control tests (live PostgreSQL)
# --------------------------------------------------------------------------


@pytest.mark.requires_database
def test_normal_proxy_control(test_db_url: str, pg_engine: Engine) -> None:
    table = _unique_table()
    with pg_engine.begin() as conn:
        conn.execute(text(f"CREATE TABLE {table} (id integer primary key, note text)"))
    try:
        with PgFaultProxy(test_db_url) as proxy:
            assert proxy.started.wait(2.0)
            db = _open_db(proxy.build_proxied_url(test_db_url))
            try:
                db._scoped.execute(text(f"INSERT INTO {table} (id, note) VALUES (1, 'ok')"))
                db._scoped.commit()
            finally:
                db.close()
            assert proxy.wait_for_error(0.5) is None
        with pg_engine.connect() as conn:
            assert conn.execute(text(f"SELECT note FROM {table} WHERE id = 1")).scalar_one() == "ok"
    finally:
        with pg_engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))


@pytest.mark.requires_database
def test_concurrent_connections_isolate_faults(test_db_url: str, pg_engine: Engine) -> None:
    """Requirement 9: one faulted connection must not leak into a concurrent one.

    D3D-B plan step 4 (concurrency with D2R) depends on this per-connection
    isolation guarantee.
    """
    table = _unique_table()
    with pg_engine.begin() as conn:
        conn.execute(text(f"CREATE TABLE {table} (id integer primary key)"))
    try:
        with PgFaultProxy(test_db_url) as proxy:
            db_a = _open_db(proxy.build_proxied_url(test_db_url))
            db_b = _open_db(proxy.build_proxied_url(test_db_url))
            try:
                # Both connections are live and have an open transaction before arming.
                db_a._scoped.execute(text(f"INSERT INTO {table} (id) VALUES (1)"))
                db_b._scoped.execute(text(f"INSERT INTO {table} (id) VALUES (2)"))
                proxy.arm(PgFaultMode.DROP_ACK)
                # Only connection A's COMMIT is in flight, so it consumes the one-shot fault.
                with pytest.raises(DBAPIError) as excinfo:
                    db_a._scoped.commit()
                assert _pgcode(excinfo.value) is None
                assert proxy.backend_committed.wait(10.0)
                assert proxy.fault_applied.wait(10.0)
                # Concurrent connection B stays transparent: its COMMIT succeeds.
                db_b._scoped.commit()
            finally:
                db_a.close()
                db_b.close()
            assert proxy.wait_for_error(0.5) is None
        assert proxy.active_connection_count() == 0
        # Both connections' work persisted: A committed despite the dropped ack, B transparently.
        with pg_engine.connect() as conn:
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 2
    finally:
        with pg_engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))


@pytest.mark.requires_database
def test_one_shot_arming_faults_only_the_next_commit(test_db_url: str, pg_engine: Engine) -> None:
    table = _unique_table()
    with pg_engine.begin() as conn:
        conn.execute(text(f"CREATE TABLE {table} (id integer primary key)"))
    try:
        with PgFaultProxy(test_db_url) as proxy:
            proxy.arm(PgFaultMode.DROP_ACK)
            db = _open_db(proxy.build_proxied_url(test_db_url))
            try:
                with pytest.raises(DBAPIError) as excinfo:
                    db._scoped.execute(text(f"INSERT INTO {table} (id) VALUES (1)"))
                    db._scoped.commit()
                assert _pgcode(excinfo.value) is None
                assert proxy.backend_committed.wait(10.0)
                assert proxy.fault_applied.wait(10.0)
            finally:
                db.close()
            # The armed fault is consumed. Clear the per-fault events and prove the
            # NEXT commit on the SAME proxy is transparent (fault_applied does not re-fire).
            proxy.fault_applied.clear()
            proxy.backend_committed.clear()
            db2 = _open_db(proxy.build_proxied_url(test_db_url))
            try:
                db2._scoped.execute(text(f"INSERT INTO {table} (id) VALUES (2)"))
                db2._scoped.commit()
            finally:
                db2.close()
            assert not proxy.fault_applied.is_set()
            assert not proxy.backend_committed.is_set()
            assert proxy.wait_for_error(0.5) is None
        with pg_engine.connect() as conn:
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 2
    finally:
        with pg_engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))


@pytest.mark.requires_database
def test_drop_ack_control(test_db_url: str, pg_engine: Engine) -> None:
    table = _unique_table()
    with pg_engine.begin() as conn:
        conn.execute(text(f"CREATE TABLE {table} (id integer primary key)"))
    try:
        with PgFaultProxy(test_db_url) as proxy:
            proxy.arm(PgFaultMode.DROP_ACK)
            db = _open_db(proxy.build_proxied_url(test_db_url))
            try:
                with pytest.raises(DBAPIError) as excinfo:
                    db._scoped.execute(text(f"INSERT INTO {table} (id) VALUES (1)"))
                    db._scoped.commit()
            finally:
                db.close()
            assert _pgcode(excinfo.value) is None
            # Pin the exact driver class D3D-B's AMBIGUOUS_COMMIT evidence observes.
            assert isinstance(_orig_error(excinfo.value), psycopg2.OperationalError)
            assert proxy.backend_committed.wait(10.0)
            assert proxy.fault_applied.wait(10.0)
        assert proxy.active_connection_count() == 0
        # Convergence only (never provenance): the server did commit.
        with pg_engine.connect() as conn:
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 1
    finally:
        with pg_engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))


@pytest.mark.requires_database
def test_sever_control(test_db_url: str, pg_engine: Engine) -> None:
    table = _unique_table()
    with pg_engine.begin() as conn:
        conn.execute(text(f"CREATE TABLE {table} (id integer primary key)"))
    try:
        proxy = PgFaultProxy(test_db_url)
        with proxy:
            proxy.arm(PgFaultMode.SEVER)
            db = _open_db(proxy.build_proxied_url(test_db_url))
            try:
                with pytest.raises(DBAPIError) as excinfo:
                    db._scoped.execute(text(f"INSERT INTO {table} (id) VALUES (1)"))
                    db._scoped.commit()
            finally:
                db.close()
            assert _pgcode(excinfo.value) is None
            # Pin the exact driver class D3D-B's AMBIGUOUS_COMMIT evidence observes.
            assert isinstance(_orig_error(excinfo.value), psycopg2.OperationalError)
            assert proxy.fault_applied.wait(10.0)
        assert proxy.active_connection_count() == 0
        with pg_engine.connect() as conn:
            assert conn.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        with pg_engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))


# --------------------------------------------------------------------------
# Negative tests (no live PostgreSQL)
# --------------------------------------------------------------------------


def test_credential_redaction_never_renders_password() -> None:
    """DD §8/§15: the password must never reach any harness repr/log surface."""
    direct_url = "postgresql+psycopg2://nomarr:topsecret@127.0.0.1:5432/postgres"

    redacted = redact_url(direct_url)
    assert "topsecret" not in redacted
    assert "127.0.0.1" in redacted and ":5432" in redacted and "postgres" in redacted

    proxy = PgFaultProxy(direct_url)
    assert "topsecret" not in proxy.redacted_backend_url
    assert "127.0.0.1" in proxy.redacted_backend_url and "postgres" in proxy.redacted_backend_url
    assert "topsecret" not in repr(proxy)

    # Same username==password case: the rendered URL must still hide the password field.
    same = "postgresql+psycopg2://nomarr:nomarr@127.0.0.1:5432/postgres"
    assert ":nomarr@" not in redact_url(same)


def test_stop_and_disarm_are_idempotent_and_leak_free() -> None:
    with _silent_backend() as backend_port:
        proxy = PgFaultProxy(_dummy_url(backend_port), backend_read_timeout=2.0, stop_timeout=1.0)
        proxy.start()
        assert proxy.started.wait(2.0)
        proxy.arm(PgFaultMode.DROP_ACK)
        proxy.disarm()
        proxy.disarm()  # idempotent
        proxy.stop()
        proxy.stop()  # idempotent, must not hang
    assert proxy.finished.is_set()
    assert proxy.active_connection_count() == 0
    assert proxy.last_error() is None


def test_malformed_frame_surfaces_typed_error() -> None:
    with _silent_backend() as backend_port, PgFaultProxy(_dummy_url(backend_port), backend_read_timeout=2.0) as proxy:
        client = socket.create_connection(proxy.address, timeout=3.0)
        try:
            client.sendall(b"\x00\x00\x00\x04")  # startup length 4 < 8 => malformed
            error = proxy.wait_for_error(3.0)
        finally:
            client.close()
    assert isinstance(error, FaultHarnessError)
    assert not isinstance(error, HarnessTimeoutError)


def test_unavailable_backend_surfaces_infrastructure_error() -> None:
    closed_port = _unused_port()
    with PgFaultProxy(_dummy_url(closed_port), backend_read_timeout=2.0) as proxy:
        client = socket.create_connection(proxy.address, timeout=3.0)
        try:
            error = proxy.wait_for_error(3.0)
        finally:
            client.close()
    assert isinstance(error, HarnessInfrastructureError)
    assert not isinstance(error, HarnessTimeoutError)


def test_timeout_surfaces_typed_timeout_error() -> None:
    with _silent_backend() as backend_port, PgFaultProxy(_dummy_url(backend_port), backend_read_timeout=1.0) as proxy:
        proxy.arm(PgFaultMode.DROP_ACK)
        client = socket.create_connection(proxy.address, timeout=3.0)
        try:
            client.sendall(_startup_message() + _query_message("COMMIT"))
            assert proxy.commit_forwarded.wait(3.0)
            error = proxy.wait_for_error(4.0)
        finally:
            client.close()
    assert isinstance(error, HarnessTimeoutError)


# --------------------------------------------------------------------------
# Socket-only guards for the Round-1 DROP_ACK commit validation and relay
# partial-frame desync handling. A minimal canned backend speaks just enough
# PostgreSQL wire protocol (startup -> AuthenticationOk + ReadyForQuery, then a
# canned reply to the Query COMMIT) so no live server is involved.
# --------------------------------------------------------------------------


def _frame(mtype: bytes, payload: bytes) -> bytes:
    return mtype + struct.pack(">I", 4 + len(payload)) + payload


def _ready_for_query(status: bytes = b"I") -> bytes:
    return _frame(b"Z", status)


def _command_complete(tag: bytes) -> bytes:
    return _frame(b"C", tag + b"\x00")


@contextlib.contextmanager
def _canned_backend(
    commit_reply: list[bytes] | None = None, *, raw_after_startup: bytes | None = None
) -> Iterator[int]:
    """A minimal PostgreSQL wire backend speaking just enough protocol.

    Always consumes the startup message and answers AuthenticationOk +
    ReadyForQuery so the proxy's synchronous startup relay completes. Then:

    * ``commit_reply``: wait for a frontend Query frame, then emit these bytes.
    * ``raw_after_startup``: emit these raw bytes immediately after the startup
      ack (used to inject a partial backend frame that stalls).
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    listener.settimeout(_ACCEPT_TIMEOUT)
    port = int(listener.getsockname()[1])
    stop = threading.Event()
    held: list[socket.socket] = []

    def serve() -> None:
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            held.append(conn)
            threading.Thread(
                target=_serve_canned,
                args=(conn, commit_reply, raw_after_startup, stop),
                daemon=True,
            ).start()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        stop.set()
        with contextlib.suppress(OSError):
            listener.close()
        for conn in held:
            with contextlib.suppress(OSError):
                conn.close()
        thread.join(timeout=2.0)


def _serve_canned(
    conn: socket.socket,
    commit_reply: list[bytes] | None,
    raw_after_startup: bytes | None,
    stop: threading.Event,
) -> None:
    conn.settimeout(_ACCEPT_TIMEOUT)
    with contextlib.suppress(OSError):
        # Consume the startup message (4-byte length + payload) before answering.
        length = _recv_exact_socket(conn, 4, stop)
        if length is None:
            return
        body = _recv_exact_socket(conn, int.from_bytes(length, "big") - 4, stop)
        if body is None:
            return
        conn.sendall(_frame(b"R", struct.pack(">I", 0)))  # AuthenticationOk
        conn.sendall(_ready_for_query())
        if raw_after_startup is not None:
            conn.sendall(raw_after_startup)
            stop.wait(2.0)
            return
        # Wait for the frontend Query COMMIT, then emit the canned reply.
        mtype = _recv_exact_socket(conn, 1, stop)
        if mtype is None:
            return
        length = _recv_exact_socket(conn, 4, stop)
        if length is None:
            return
        payload = _recv_exact_socket(conn, int.from_bytes(length, "big") - 4, stop)
        if payload is None:
            return
        for chunk in commit_reply or []:
            conn.sendall(chunk)
        stop.wait(2.0)


def _recv_exact_socket(conn: socket.socket, size: int, stop: threading.Event) -> bytes | None:
    buffer = bytearray()
    while len(buffer) < size:
        if stop.is_set():
            return None
        try:
            chunk = conn.recv(size - len(buffer))
        except TimeoutError:
            continue
        except OSError:
            return None
        if not chunk:
            return None
        buffer.extend(chunk)
    return bytes(buffer)


def _drive_drop_ack(commit_reply: list[bytes]) -> tuple[FaultHarnessError | None, PgFaultProxy]:
    """Arm DROP_ACK against a canned backend and return the recorded error + proxy."""
    with (
        _canned_backend(commit_reply) as backend_port,
        PgFaultProxy(_dummy_url(backend_port), backend_read_timeout=2.0, stop_timeout=1.0) as proxy,
    ):
        proxy.arm(PgFaultMode.DROP_ACK)
        client = socket.create_connection(proxy.address, timeout=3.0)
        try:
            client.sendall(_startup_message() + _query_message("COMMIT"))
            assert proxy.commit_forwarded.wait(3.0)
            error = proxy.wait_for_error(4.0)
        finally:
            client.close()
        return error, proxy


def test_drop_ack_ready_without_commit_command_complete_is_rejected() -> None:
    """DROP_ACK must not set backend_committed on a ReadyForQuery with no COMMIT tag."""
    error, proxy = _drive_drop_ack([_command_complete(b"INSERT 0 1"), _ready_for_query(b"I")])
    assert isinstance(error, HarnessInfrastructureError)
    assert not proxy.backend_committed.is_set()
    assert not proxy.fault_applied.is_set()


def test_drop_ack_non_idle_ready_for_query_is_rejected() -> None:
    """DROP_ACK must not set backend_committed on a non-idle ReadyForQuery status."""
    error, proxy = _drive_drop_ack([_command_complete(b"COMMIT"), _ready_for_query(b"E")])
    assert isinstance(error, HarnessInfrastructureError)
    assert not proxy.backend_committed.is_set()
    assert not proxy.fault_applied.is_set()


def test_mid_frame_client_side_desync_is_infrastructure_error() -> None:
    """A partial frontend frame must record infrastructure error, not HarnessTimeoutError."""
    with (
        _silent_backend() as backend_port,
        PgFaultProxy(_dummy_url(backend_port), backend_read_timeout=1.0, stop_timeout=1.0) as proxy,
    ):
        client = socket.create_connection(proxy.address, timeout=3.0)
        try:
            client.sendall(_startup_message())
            # Type byte + partial length, then stall: the relay consumes the type
            # byte and must not misparse a following byte as a new frame type.
            client.sendall(b"Q\x00\x00")
            error = proxy.wait_for_error(4.0)
        finally:
            client.close()
    assert error is not None
    assert isinstance(error, HarnessInfrastructureError)
    assert not isinstance(error, HarnessTimeoutError)
    assert proxy.active_connection_count() == 0


def test_mid_frame_backend_side_desync_is_infrastructure_error() -> None:
    """A partial backend frame must record infrastructure error, not HarnessTimeoutError."""
    with (
        _canned_backend(raw_after_startup=b"C\x00\x00") as backend_port,
        PgFaultProxy(_dummy_url(backend_port), backend_read_timeout=1.0, stop_timeout=1.0) as proxy,
    ):
        client = socket.create_connection(proxy.address, timeout=3.0)
        try:
            client.sendall(_startup_message())
            # The canned backend emits a partial frame (type byte + partial length)
            # then stalls; the relay consumes the type byte and must close rather
            # than misparse the next byte as a new message type.
            error = proxy.wait_for_error(4.0)
        finally:
            client.close()
    assert error is not None
    assert isinstance(error, HarnessInfrastructureError)
    assert not isinstance(error, HarnessTimeoutError)
    assert proxy.active_connection_count() == 0
