"""Components layer - heavy domain logic modules.

This layer contains "thick" domain modules that implement the heavy lifting:
- Complex loops, I/O operations, algorithmic logic
- Tag aggregation, ML inference, analytics computation
- File writing, audio processing, calibration

Components are leaf modules that:
- Do NOT import services, workflows, or interfaces
- ARE imported and used BY workflows and services
- May import from: helpers, persistence, other components

Architecture:
- helpers/ = stdlib-only utilities (pure, stateless)
- components/ = domain logic building blocks (this layer)
- workflows/ = orchestration of components + persistence
- services/ = DI, wiring, long-lived resources
- interfaces/ = HTTP/CLI/Web presentation
"""
