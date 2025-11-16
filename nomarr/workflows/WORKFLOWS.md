WORKFLOW NAMING & STRUCTURE

1. File naming

   - One main workflow per file.
   - File name: verb_object.py
     Examples:
     scan_library.py
     tag_audio_file.py
     enqueue_files.py
     generate_calibration.py
     recalibrate_file.py

2. Function naming

   - Primary entrypoint: verb_object_workflow(...)
   - Everything else in the module is:
     - a private helper (\_something_internal), or
     - a very closely related variant.

3. Size / complexity

   - Soft limit: ~300–400 LOC per workflow module.
   - If the file has multiple exported workflows that are different user stories,
     split into multiple files.
   - Exceptions: "analytics-style" modules can group a few related
     read-only workflows (e.g. analytics.py) as long as they stay cohesive.

4. Layering rules
   - Workflows NEVER import services or nomarr.app.
   - Workflows may import:
     - nomarr.ml.\*
     - nomarr.tagging.\*
     - nomarr.persistence.\*
     - nomarr.helpers.\*
   - Services call workflows; interfaces call services.
