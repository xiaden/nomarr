"""ML resource management — VRAM coordination, capacity probing, tier selection.

Components for managing ML runtime resources:
- VRAM promise registration and fleet-wide coordination
- GPU capacity probing and estimation
- Execution tier selection (GPU/CPU fallback)
- Worker context registration
- Timing and OOM helper utilities

These components are used by processing workflows and the worker system;
they are not re-exported through the parent ``ml`` package.
"""
