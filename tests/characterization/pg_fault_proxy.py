"""Test-only PostgreSQL TCP fault-injection proxy (D3D-A mood fault harness).

This module is test-only support located under tracked ``tests/characterization/``: it
contains no production code and is not imported by anything under ``nomarr/``. It sits at the TCP boundary between a
PostgreSQL driver (psycopg2/SQLAlchemy) and the real server and deterministically
induces one of three pgcode-less faults on demand:

``DROP_ACK``
    Commit-phase. Forward the owner transaction's ``COMMIT`` to the backend, let the
    backend actually complete the commit, observe the backend acknowledgement
    (``CommandComplete('COMMIT')`` + ``ReadyForQuery`` with idle status ``'I'``),
    then *discard* that acknowledgement and close both the client and backend
    sockets. The driver observes a pgcode-less ``DBAPIError`` even though the server
    committed.

``SEVER``
    Commit-phase. Forward the ``COMMIT`` and then sever both sockets during an
    explicitly synchronized commit-phase window, before forwarding any backend
    acknowledgement. The driver observes a pgcode-less connection-closed
    ``DBAPIError``.

``SEVER_PRE_COMMIT``
    Pre-commit. Sever both sockets on the first frontend frame, before any
    ``COMMIT`` is forwarded. The driver observes a pgcode-less connection-closed
    ``DBAPIError``, but the failure is strictly before the commit phase.

``DROP_ACK`` and ``SEVER`` are the driver-observable preconditions the mood
repository maps to ``AMBIGUOUS_COMMIT`` (see ``song_tag_repo._commit_mood_batch``).
``SEVER_PRE_COMMIT`` is the contrasting pre-commit fault: because no ``COMMIT`` was
ever forwarded the owner classifies it as ``INFRA_FAILURE``, never
``AMBIGUOUS_COMMIT``. This harness asserts the driver/harness-level signature only;
the mood-path ``MoodBatchResult`` proof belongs to D3D-B.

Design constraints honored here:

* No monkeypatching of production symbols -- the fault is induced purely by
  manipulating the real TCP byte stream.
* No production imports, no runtime hooks, no new dependencies (stdlib only
  plus SQLAlchemy's URL parser for the helper).
* Plaintext only: the proxied URL built by :func:`build_proxied_url` forces
  ``sslmode=disable`` because the harness cannot inspect TLS-encrypted bytes.
* Credentials are never rendered by any harness error or ``repr``.

Empirical driver commit path (native PostgreSQL 17.11, psycopg2 2.9.12,
SQLAlchemy 2.0.52): with ``sslmode=disable`` psycopg2 emits ``BEGIN``,
``SELECT ...`` and ``COMMIT`` as *simple Query* (``Q``) messages. The extended
protocol (``Parse``/``Execute``) path is handled defensively but is not
exercised by psycopg2's ``connection.commit()``.
"""

from __future__ import annotations

import contextlib
import socket
import threading
from enum import Enum

from sqlalchemy.engine import make_url

__all__ = [
    "FaultHarnessError",
    "HarnessInfrastructureError",
    "HarnessTimeoutError",
    "PgFaultMode",
    "PgFaultProxy",
    "build_proxied_url",
    "redact_url",
]

LOOPBACK_HOST = "127.0.0.1"

_SSL_REQUEST_CODE = 80877103
_GSSENC_REQUEST_CODE = 80877104
_MAX_FRAME_BYTES = 64 * 1024 * 1024
_DEFAULT_BACKEND_READ_TIMEOUT = 30.0
_DEFAULT_STOP_TIMEOUT = 5.0
_LISTENER_POLL_TIMEOUT = 0.2


class FaultHarnessError(RuntimeError):
    """Base class for test-only harness failures.

    A :class:`FaultHarnessError` is always an infrastructure/test-support
    failure. It is never a mood result and never a driver commit outcome.
    """


class HarnessInfrastructureError(FaultHarnessError):
    """Harness setup/transport failure (infrastructure, potentially retryable)."""


class HarnessTimeoutError(HarnessInfrastructureError):
    """The harness did not observe a required peer event within its budget.

    ``partial`` is True when a frame read timed out after consuming part of the
    frame. The relay is then desynchronized (the next byte would be misread as a
    new message type) and the caller must close the connection instead of
    treating the timeout as an idle peer and retrying the read.
    """

    def __init__(self, message: str, *, partial: bool = False) -> None:
        super().__init__(message)
        self.partial = partial


class PgFaultMode(Enum):
    """One-shot fault to apply to the next observed ``COMMIT`` or frontend frame.

    ``DROP_ACK`` and ``SEVER`` fault the next ``COMMIT`` (post-commit-forward
    ambiguity). ``SEVER_PRE_COMMIT`` severs both sockets on the next frontend
    frame *before* any ``COMMIT`` is forwarded, modelling a pgcode-less
    infrastructure failure that occurs strictly before the commit phase.
    """

    DROP_ACK = "DROP_ACK"
    SEVER = "SEVER"
    SEVER_PRE_COMMIT = "SEVER_PRE_COMMIT"


def redact_url(url: str) -> str:
    """Return ``url`` with any password replaced, for safe display/logging."""
    try:
        return make_url(url).render_as_string(hide_password=True)
    except Exception:
        return "<unparseable-url-redacted>"


def build_proxied_url(direct_url: str, *, host: str = LOOPBACK_HOST, port: int) -> str:
    """Build a host/port-overridden URL for the proxy, preserving the driver scheme.

    The scheme (e.g. ``postgresql+psycopg2``) is inherited from ``direct_url``.
    User, password, database and all query parameters are preserved. The
    ``sslmode`` parameter is forced to ``disable`` because the harness parses the
    plaintext PostgreSQL byte stream and cannot inspect TLS-encrypted traffic.
    """
    url = make_url(direct_url)
    proxied = url.set(host=host, port=port).update_query_dict({"sslmode": "disable"})
    return proxied.render_as_string(hide_password=False)


def _normalize_sql(raw: bytes) -> str:
    """Extract and normalize the SQL text of a frontend message payload."""
    text = raw.split(b"\x00", 1)[0].decode("ascii", errors="replace")
    return text.strip().rstrip(";").strip().upper()


class _CommitPhase:
    """Per-connection fault state shared by a connection's relay threads."""

    __slots__ = ("mode",)

    def __init__(self) -> None:
        self.mode: PgFaultMode | None = None


class PgFaultProxy:
    """A loopback TCP proxy that can inject pgcode-less PostgreSQL faults.

    Both commit-phase (``DROP_ACK``, ``SEVER``) and pre-commit
    (``SEVER_PRE_COMMIT``) modes are supported.

    The proxy accepts client connections on ``127.0.0.1:<ephemeral>`` and opens a
    matching backend connection to the host/port parsed from ``backend_url``.
    Each client connection is served by one connection handler and a pair of
    relay threads, so multiple concurrent clients are supported.

    Synchronization points (all :class:`threading.Event`):

    ``started``
        Set once the listener is bound and the accept thread is running.
    ``client_connected``
        Set once a client connection has a live backend connection.
    ``commit_forwarded``
        Set after a frontend ``COMMIT`` was parsed and written to the backend.
    ``backend_committed``
        DROP_ACK only; set when the backend's ``ReadyForQuery`` for the faulted
        commit was observed (proves the server completed the commit).
    ``fault_applied``
        Set when the fault took effect: the acknowledgement has been dropped
        (DROP_ACK), both sockets have been severed during the commit phase
        (SEVER), or both sockets have been severed on the first frontend frame
        before any ``COMMIT`` (SEVER_PRE_COMMIT).
    ``finished``
        Set by :meth:`stop` after the listener and all relay threads are joined.
    ``shutdown``
        Internal shutdown signal; set by :meth:`stop`.
    """

    def __init__(
        self,
        backend_url: str,
        *,
        host: str = LOOPBACK_HOST,
        backend_read_timeout: float = _DEFAULT_BACKEND_READ_TIMEOUT,
        stop_timeout: float = _DEFAULT_STOP_TIMEOUT,
    ) -> None:
        parsed = make_url(backend_url)
        if parsed.host is None or parsed.port is None:
            raise FaultHarnessError("backend URL must include a host and port")
        self._backend_url = backend_url
        self._backend_host = parsed.host
        self._backend_port = int(parsed.port)
        self._bind_host = host
        self._backend_read_timeout = backend_read_timeout
        self._stop_timeout = stop_timeout

        self._listener: socket.socket | None = None
        self._port: int | None = None

        self.started = threading.Event()
        self.client_connected = threading.Event()
        self.commit_forwarded = threading.Event()
        self.backend_committed = threading.Event()
        self.fault_applied = threading.Event()
        self.finished = threading.Event()
        self._shutdown = threading.Event()
        self._lock = threading.Lock()
        self._armed: PgFaultMode | None = None
        self._errors: list[FaultHarnessError] = []
        self._error_event = threading.Event()
        self._sockets: set[socket.socket] = set()
        self._threads: list[threading.Thread] = []
        self._accept_thread: threading.Thread | None = None
        self._active_connections = 0
        self._connections_accepted = 0
        self._commit_count = 0
        self._stopped = False
        self._no_active_connections = threading.Event()
        self._no_active_connections.set()

    # ------------------------------------------------------------------ repr

    def __repr__(self) -> str:
        return f"PgFaultProxy(backend={redact_url(self._backend_url)!r}, port={self._port!r}, armed={self._armed!r})"

    @property
    def redacted_backend_url(self) -> str:
        """The backend URL with its password redacted."""
        return redact_url(self._backend_url)

    # -------------------------------------------------------------- lifecycle

    def start(self) -> None:
        """Bind the loopback listener and start accepting connections."""
        if self._listener is not None:
            return
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self._bind_host, 0))
        listener.listen(16)
        listener.settimeout(_LISTENER_POLL_TIMEOUT)
        self._listener = listener
        self._port = int(listener.getsockname()[1])
        self._accept_thread = threading.Thread(target=self._accept_loop, name="pg-fault-accept", daemon=True)
        self._accept_thread.start()
        self.started.set()

    def stop(self) -> None:
        """Tear down the listener and every live connection. Idempotent."""
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
        self._shutdown.set()
        listener = self._listener
        if listener is not None:
            with contextlib.suppress(OSError):
                listener.close()
        with self._lock:
            sockets = list(self._sockets)
            threads = list(self._threads)
        for sock in sockets:
            self._close_socket(sock)
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=self._stop_timeout)
        for thread in threads:
            thread.join(timeout=self._stop_timeout)
        self.finished.set()

    def __enter__(self) -> PgFaultProxy:
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.stop()

    @property
    def port(self) -> int:
        """The bound loopback listener port (raises before :meth:`start`)."""
        if self._port is None:
            raise FaultHarnessError("proxy is not started")
        return self._port

    @property
    def address(self) -> tuple[str, int]:
        """The ``(host, port)`` clients should connect to."""
        return (self._bind_host, self.port)

    # ---------------------------------------------------------------- faulting

    def arm(self, mode: PgFaultMode) -> None:
        """Arm a one-shot fault for the next observed fault point.

        Clears the per-fault synchronization events so a test can await them
        deterministically. The fault is one-shot and is consumed atomically at
        its fault point: ``DROP_ACK`` and ``SEVER`` apply to the next observed
        ``COMMIT``; ``SEVER_PRE_COMMIT`` applies to the next frontend frame and
        is consumed before any ``COMMIT`` is forwarded. Arming may happen before
        or after the connection is opened.
        """
        if not isinstance(mode, PgFaultMode):
            raise FaultHarnessError("mode must be a PgFaultMode")
        with self._lock:
            self._armed = mode
        self.client_connected.clear()
        self.commit_forwarded.clear()
        self.backend_committed.clear()
        self.fault_applied.clear()

    def disarm(self) -> None:
        """Cancel any armed (not yet applied) fault."""
        with self._lock:
            self._armed = None

    def build_proxied_url(self, direct_url: str | None = None) -> str:
        """Build a proxied URL from ``direct_url`` (defaults to the backend URL)."""
        return build_proxied_url(direct_url or self._backend_url, host=self._bind_host, port=self.port)

    # ------------------------------------------------------------- diagnostics

    @property
    def errors(self) -> tuple[FaultHarnessError, ...]:
        """Snapshot of every harness error recorded (the :class:`FaultHarnessError` family)."""
        with self._lock:
            return tuple(self._errors)

    def last_error(self) -> FaultHarnessError | None:
        """The most recently recorded harness error (the :class:`FaultHarnessError` family), if any."""
        with self._lock:
            return self._errors[-1] if self._errors else None

    def wait_for_error(self, timeout: float = _DEFAULT_STOP_TIMEOUT) -> FaultHarnessError | None:
        """Block until the harness records a :class:`FaultHarnessError`, or timeout."""
        if self._error_event.wait(timeout=timeout):
            with self._lock:
                return self._errors[0] if self._errors else None
        return None

    def active_connection_count(self) -> int:
        """Number of client connections still served by a handler thread."""
        with self._lock:
            return self._active_connections

    def wait_for_no_active_connections(self, timeout: float = _DEFAULT_STOP_TIMEOUT) -> bool:
        """Block until no client connection is still served by a handler thread.

        This is a harness handler-teardown signal only. It does NOT prove the
        driver released its session: in every fault mode the proxy severs its own
        client and backend sockets, so the handler exits and this becomes true
        regardless of driver behavior. For a genuine driver-side no-leak proof,
        read the ``Database`` engine pool while this context is still active and
        before any test-side ``close()`` (see D3D-B
        ``_assert_driver_pool_released``).
        """
        return self._no_active_connections.wait(timeout=timeout)

    @property
    def connections_accepted(self) -> int:
        """Cumulative number of client connections accepted since ``start()``.

        A retry that opens a fresh session/connection increments this; a
        no-retry assertion therefore observes exactly one accepted connection
        for a single faulted intent.
        """
        with self._lock:
            return self._connections_accepted

    @property
    def commit_count(self) -> int:
        """Cumulative number of frontend ``COMMIT`` frames forwarded to the backend.

        Each owner transaction attempt ends in exactly one forwarded ``COMMIT``,
        so a no-retry assertion observes exactly one for a single faulted intent.
        """
        with self._lock:
            return self._commit_count

    def _record_error(self, error: FaultHarnessError) -> None:
        with self._lock:
            self._errors.append(error)
        self._error_event.set()

    # -------------------------------------------------------------- internals

    def _register_socket(self, sock: socket.socket) -> None:
        with self._lock:
            self._sockets.add(sock)

    def _close_socket(self, sock: socket.socket) -> None:
        with self._lock:
            self._sockets.discard(sock)
        with contextlib.suppress(OSError):
            sock.shutdown(socket.SHUT_RDWR)
        with contextlib.suppress(OSError):
            sock.close()

    def _is_intentionally_closed(self, sock: socket.socket) -> bool:
        """True when the proxy itself already tore this socket down."""
        if self._shutdown.is_set():
            return True
        with self._lock:
            return sock not in self._sockets

    def _accept_loop(self) -> None:
        listener = self._listener
        if listener is None:
            return
        while not self._shutdown.is_set():
            try:
                client, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                if self._shutdown.is_set():
                    break
                self._record_error(HarnessInfrastructureError("proxy listener accept failed"))
                break
            thread = threading.Thread(target=self._handle_connection, args=(client,), name="pg-fault-conn", daemon=True)
            with self._lock:
                self._threads.append(thread)
                self._active_connections += 1
                self._connections_accepted += 1
                self._no_active_connections.clear()
            thread.start()

    def _handle_connection(self, client: socket.socket) -> None:
        backend: socket.socket | None = None
        try:
            self._register_socket(client)
            client.settimeout(self._backend_read_timeout)
            try:
                backend = socket.create_connection(
                    (self._backend_host, self._backend_port), timeout=self._backend_read_timeout
                )
            except OSError as exc:
                self._record_error(HarnessInfrastructureError(f"backend connect failed: {type(exc).__name__}: {exc}"))
                return
            self._register_socket(backend)
            backend.settimeout(self._backend_read_timeout)
            self.client_connected.set()
            self._perform_handshake(client, backend)
            commit_phase = _CommitPhase()
            c2b = threading.Thread(
                target=self._client_to_backend, args=(client, backend, commit_phase), name="pg-fault-c2b", daemon=True
            )
            b2c = threading.Thread(
                target=self._backend_to_client, args=(client, backend, commit_phase), name="pg-fault-b2c", daemon=True
            )
            with self._lock:
                self._threads.extend((c2b, b2c))
            c2b.start()
            b2c.start()
            c2b.join()
            b2c.join()
        except FaultHarnessError as exc:
            self._record_error(exc)
        except OSError as exc:
            if not self._shutdown.is_set():
                self._record_error(HarnessInfrastructureError(f"proxy transport failure: {type(exc).__name__}: {exc}"))
        finally:
            self._close_socket(client)
            if backend is not None:
                self._close_socket(backend)
            with self._lock:
                self._active_connections -= 1
                if self._active_connections == 0:
                    self._no_active_connections.set()

    def _perform_handshake(self, client: socket.socket, backend: socket.socket) -> None:
        """Relay the startup handshake synchronously before relay threads start."""
        while True:
            header = self._recv_exact(client, 4)
            if header is None:
                raise HarnessInfrastructureError("client closed during startup handshake")
            length = int.from_bytes(header, "big")
            if length == 8:
                body = self._recv_exact(client, 4)
                if body is None:
                    raise HarnessInfrastructureError("client closed during SSL/GSS negotiation")
                code = int.from_bytes(body, "big")
                if code not in (_SSL_REQUEST_CODE, _GSSENC_REQUEST_CODE):
                    raise FaultHarnessError(f"unsupported startup request code {code}")
                self._send_all(backend, header + body)
                response = self._recv_exact(backend, 1)
                if response is None:
                    raise HarnessTimeoutError("backend closed during SSL/GSS negotiation")
                if response == b"S":
                    raise HarnessInfrastructureError("backend negotiated TLS; the harness cannot proxy TLS")
                self._send_all(client, response)
                continue
            if length < 8 or length > _MAX_FRAME_BYTES:
                raise FaultHarnessError(f"malformed startup frame length {length}")
            payload = self._recv_exact(client, length - 4)
            if payload is None:
                raise HarnessInfrastructureError("client closed during startup message")
            self._send_all(backend, header + payload)
            return

    def _read_relay_frame(self, sock: socket.socket, label: str) -> tuple[bytes, bytes, bytes] | None:
        """Read one complete PostgreSQL frame as ``(type, length_bytes, payload)``.

        Returns ``None`` when the peer closed the connection. A timeout with no
        byte consumed raises :class:`HarnessTimeoutError` with ``partial=False``
        (idle peer). A timeout after the message type has been consumed raises it
        with ``partial=True``: the relay is desynchronized and the caller must
        close the connection rather than discard the partial frame and misread
        the next byte as a new message type.
        """
        try:
            mtype = self._recv_exact(sock, 1)
        except HarnessTimeoutError as exc:
            raise HarnessTimeoutError(f"idle {label}: no frame byte received") from exc
        if mtype is None:
            return None
        try:
            length_bytes = self._recv_exact(sock, 4)
            if length_bytes is None:
                return None
            length = int.from_bytes(length_bytes, "big")
            if length < 4 or length > _MAX_FRAME_BYTES:
                raise FaultHarnessError(f"malformed {label} message length {length}")
            payload = self._recv_exact(sock, length - 4)
        except HarnessTimeoutError as exc:
            raise HarnessTimeoutError(f"mid-frame {label} timeout after partial read", partial=True) from exc
        if payload is None:
            return None
        return mtype, length_bytes, payload

    def _client_to_backend(self, client: socket.socket, backend: socket.socket, commit_phase: _CommitPhase) -> None:
        pending_commit = False
        try:
            while not self._shutdown.is_set():
                try:
                    frame = self._read_relay_frame(client, "frontend")
                except HarnessTimeoutError as exc:
                    if exc.partial:
                        self._record_error(
                            HarnessInfrastructureError(
                                "mid-frame client timeout desynchronized the relay; closing connection"
                            )
                        )
                        break
                    continue  # idle client: keep the connection open
                if frame is None:
                    break
                if self._consume_pre_commit_fault(client, backend):
                    break
                mtype, length_bytes, payload = frame
                raw = mtype + length_bytes + payload
                if mtype == b"Q":
                    if _normalize_sql(payload) == "COMMIT":
                        self._forward_commit(client, backend, raw, commit_phase)
                    else:
                        self._send_all(backend, raw)
                elif mtype == b"P":
                    pending_commit = self._parse_message_sql(payload) == "COMMIT"
                    self._send_all(backend, raw)
                elif mtype == b"E" and pending_commit:
                    pending_commit = False
                    self._forward_commit(client, backend, raw, commit_phase)
                else:
                    self._send_all(backend, raw)
        except FaultHarnessError as exc:
            self._record_error(exc)
        except OSError as exc:
            if not self._shutdown.is_set():
                self._record_error(HarnessInfrastructureError(f"proxy transport failure: {type(exc).__name__}: {exc}"))
        finally:
            self._close_socket(client)
            self._close_socket(backend)

    def _backend_to_client(self, client: socket.socket, backend: socket.socket, commit_phase: _CommitPhase) -> None:
        commit_command_complete_seen = False
        try:
            while not self._shutdown.is_set():
                try:
                    frame = self._read_relay_frame(backend, "backend")
                except HarnessTimeoutError as exc:
                    if exc.partial:
                        self._record_error(
                            HarnessInfrastructureError(
                                "mid-frame backend timeout desynchronized the relay; closing connection"
                            )
                        )
                        break
                    if commit_phase.mode is PgFaultMode.DROP_ACK:
                        self._record_error(HarnessTimeoutError("backend acknowledgement not observed within timeout"))
                        break
                    continue  # idle backend: keep the connection open
                if frame is None:
                    break
                mtype, length_bytes, payload = frame
                raw = mtype + length_bytes + payload
                if commit_phase.mode is PgFaultMode.DROP_ACK:
                    if mtype == b"C":
                        commit_command_complete_seen = payload.rstrip(b"\x00") == b"COMMIT"
                        continue
                    if mtype == b"Z":
                        if not commit_command_complete_seen:
                            self._record_error(
                                HarnessInfrastructureError(
                                    "DROP_ACK: ReadyForQuery without a COMMIT CommandComplete; commit unverified"
                                )
                            )
                            break
                        if payload != b"I":
                            self._record_error(
                                HarnessInfrastructureError(
                                    f"DROP_ACK: ReadyForQuery status {payload!r} is not idle; commit unverified"
                                )
                            )
                            break
                        self.backend_committed.set()
                        self.fault_applied.set()
                        break  # drop the acknowledgement: never forward it
                    continue  # discard remaining ack bytes for this commit
                if commit_phase.mode is PgFaultMode.SEVER:
                    break
                self._send_all(client, raw)
        except FaultHarnessError as exc:
            self._record_error(exc)
        except OSError as exc:
            if not self._shutdown.is_set():
                self._record_error(HarnessInfrastructureError(f"proxy transport failure: {type(exc).__name__}: {exc}"))
        finally:
            self._close_socket(client)
            self._close_socket(backend)

    def _forward_commit(
        self, client: socket.socket, backend: socket.socket, raw: bytes, commit_phase: _CommitPhase
    ) -> None:
        with self._lock:
            mode = self._armed
            self._armed = None
            commit_phase.mode = mode
            self._commit_count += 1
        self._send_all(backend, raw)
        self.commit_forwarded.set()
        if mode is PgFaultMode.SEVER:
            self.fault_applied.set()
            self._close_socket(client)
            self._close_socket(backend)

    def _consume_pre_commit_fault(self, client: socket.socket, backend: socket.socket) -> bool:
        """Sever both sockets on the next frontend frame when pre-commit armed.

        ``SEVER_PRE_COMMIT`` is consumed atomically so it applies once; the
        frame that triggered it is *not* forwarded (the failure is strictly
        before the commit phase). Returns True when the connection was severed.
        """
        with self._lock:
            if self._armed is not PgFaultMode.SEVER_PRE_COMMIT:
                return False
            self._armed = None
        self.fault_applied.set()
        self._close_socket(client)
        self._close_socket(backend)
        return True

    @staticmethod
    def _parse_message_sql(payload: bytes) -> str:
        separator = payload.find(b"\x00")
        if separator < 0:
            raise FaultHarnessError("malformed Parse message: missing statement-name terminator")
        return _normalize_sql(payload[separator + 1 :])

    def _recv_exact(self, sock: socket.socket, size: int) -> bytes | None:
        buffer = bytearray()
        while len(buffer) < size:
            try:
                chunk = sock.recv(size - len(buffer))
            except TimeoutError as exc:
                raise HarnessTimeoutError(f"timed out waiting for {size} bytes") from exc
            except OSError as exc:
                if self._is_intentionally_closed(sock):
                    return None
                raise HarnessInfrastructureError(f"socket read failed: {type(exc).__name__}: {exc}") from exc
            if not chunk:
                return None
            buffer.extend(chunk)
        return bytes(buffer)

    def _send_all(self, sock: socket.socket, data: bytes) -> None:
        try:
            sock.sendall(data)
        except OSError as exc:
            if self._is_intentionally_closed(sock):
                return
            raise HarnessInfrastructureError(f"socket write failed: {type(exc).__name__}: {exc}") from exc
