# nomarr.interfaces.api.event_broker

API reference for `nomarr.interfaces.api.event_broker`.

---

## Classes

### StateBroker

Thread-safe state broker for SSE-based state synchronization.

**Methods:**

- `__init__(self)`
- `get_client_count(self) -> 'int'`
- `get_stats(self) -> 'dict[str, Any]'`
- `remove_job(self, job_id: 'int')`
- `subscribe(self, topics: 'list[str]') -> 'tuple[str, queue.Queue]'`
- `unsubscribe(self, client_id: 'str')`
- `update_job_state(self, job_id: 'int', **kwargs)`
- `update_queue_state(self, **kwargs)`
- `update_worker_state(self, worker_id: 'int', **kwargs)`

---
