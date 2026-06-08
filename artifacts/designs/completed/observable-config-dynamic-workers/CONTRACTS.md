# Contracts Ledger — Observable Config and Dynamic Worker Scaling

## Plan A: Worker Lifecycle

| Exported Symbol | Signature | Notes |
|---|---|---|
| `WorkerSystemService.add_workers` | `(self, count: int) -> None` | Phase 2. Adds `count` workers with sequential indices. Guards: `count <= 0`, `_tier_selection is None`, empty pool. |
| `WorkerSystemService.remove_workers` | `(self, count: int) -> None` | Phase 2. Removes last `count` workers via `stop()` + `join(2.0)`. Guards: `count <= 0`, `count >= len(self._workers)` → delegates to `stop_all_workers()`. |
| `WorkerSystemService.get_worker_count` | `(self) -> int` | Phase 2 (Plan B amendment). Returns `len(self._workers)`. Public API for current pool size — callers must not access `_workers` directly. |

## Plan B: Config Subscription + Wiring

| Exported Symbol | Signature | Notes |
|---|---|---|
| `OBSERVABLE_KEYS` | `frozenset[str] = frozenset({"tagger_worker_count"})` | `config_schema.py:262`. Allowlist of keys that support runtime subscription. |
| `ConfigService._subscriptions` | `dict[str, list[Callable[[str, Any], Coroutine[Any, Any, None]]]]` | `config_svc.py:92`. Per-key callback registry. |
| `ConfigService.subscribe` | `(self, key: str, callback: Callable[[str, Any], Coroutine[Any, Any, None]]) -> None` | `config_svc.py:156`. Raises `ValueError` if key not in `OBSERVABLE_KEYS`. |
| `ConfigService.set` (modified) | `(self, key: str, value: Any) -> None` | `config_svc.py:121`. Fires callbacks via `asyncio.create_task()` after cache+DB write for observable keys. |
| `Application._on_tagger_worker_count_changed` | `async (self, key: str, value: Any) -> None` | `app.py:435`. Uses `ConfigService.get_worker_count("tagger")` for desired count (1-8 clamped), `WorkerSystemService.get_worker_count()` for current count. Computes delta, delegates to `add_workers()`/`remove_workers()`. |

## Decisions

| Plan | Decision | Rationale |
|---|---|---|
| A | Per-worker `Event()` replaces shared `_stop_event`; `_shutting_down` bool guards restart logic | Each worker must be independently stoppable for scale-down; DiscoveryWorker already checks its event opaquely — no worker-side changes needed |
| A | `add_workers` skips admission control re-evaluation if pool is already running | Capacity already proven at initial start; re-probing would be wasted cycles |
| A | `remove_workers` signals stop events then `join(2.0)` — no `terminate()`/`kill()` in normal flow | Workers drain naturally; force-kill only as fallback if `join` times out |
| B | `Coroutine` type instead of `Awaitable` for subscribe callbacks | `asyncio.create_task()` requires a concrete coroutine, not just any awaitable |
| B | Added `get_worker_count()` public method to `WorkerSystemService` | Plan prescribed accessing private `_workers`; public API avoids coupling to implementation |
| B | Callback uses `ConfigService.get_worker_count("tagger")` for desired count | `get_worker_count()` already handles the `None→auto` and 1-8 clamping logic — don't duplicate it |
