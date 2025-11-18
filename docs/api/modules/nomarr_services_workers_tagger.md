# nomarr.services.workers.tagger

API reference for `nomarr.services.workers.tagger`.

---

## Functions

### create_tagger_worker(db: 'Database', queue: 'ProcessingQueue', event_broker: 'Any', interval: 'int' = 2, worker_id: 'int' = 0) -> 'BaseWorker'

Create a TaggerWorker for ML-based audio file tagging.

---
