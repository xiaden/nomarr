"""Database repository classes — PostgreSQL persistence helpers.

This package contains repository classes organized by domain/table:

- ``LibraryRepository`` — ``libraries`` table
- ``SongRepository`` — ``songs`` table
- ``FolderRepository`` — ``library_folders`` table
- ``TagRepository`` — ``tags`` table
- ``SongTagRepository`` — ``song_tags`` junction table
- ``ScanRepository`` — ``library_scans`` table
- ``AppRepository`` — KV tables (locks, health, meta, sessions, worker claims, …)
- ``PipelineRepository`` — ``pipeline_states`` table
- ``SongStateRepository`` — ``song_states`` and ``song_state_assignments`` tables
- ``ModelRepo`` — ``ml_models`` table
- ``OutputRepo`` — ``ml_model_outputs`` and ``ml_output_streams`` tables
- ``CalibrationRepo`` — ``calibration_states`` and ``calibration_history`` tables
- ``EmbeddingStreamRepository`` — ``ml_embedding_streams`` table
"""
