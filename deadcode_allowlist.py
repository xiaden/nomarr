# deadcode_allowlist.py — vulture allowlist
#
# This file tells vulture about names that are used but not visible to static analysis.
# Vulture sees these stub definitions and skips them in its unused-code reports.
#
# Categories covered:
# 1. Alembic migration entry points
# 2. FastAPI dependency injection functions (Depends())
# 3. FastAPI route handlers (web_* functions)
# 4. VRAM worker entry points
# 5. Pydantic Settings attributes (accessed via model_dump(), dict(), etc.)
# 6. TypedDict/dataclass result types (used in type position)
# 7. Component public API functions (imported by services/workflows dynamically)
# 8. Event handlers and magic methods
# 9. Helper functions (used by other modules)
# 10. Internal helper functions (prefixed with _)
# 11. Unused variables (local scope assignments)
# 12. Classes that are used but flagged as unused
# 13. Additional TypedDict fields and dataclass attributes
#
# Add new entries here when vulture flags legitimate code that is used via:
# - Dynamic dispatch (getattr, importlib)
# - FastAPI decorators (@router.get, Depends())
# - Pydantic model field access
# - Alembic migration framework
# - Worker process entry points

# ---------------------------------------------------------------------------
# 1. Alembic migration entry points
# ---------------------------------------------------------------------------
def upgrade():
    pass  # Alembic migration entry point (called by alembic CLI)


def downgrade():
    pass  # Alembic migration entry point (called by alembic CLI)


def run_migrations_online():
    pass  # Alembic env.py entry point


def run_migrations_offline():
    pass  # Alembic env.py entry point


def do_run_migrations():
    pass  # Alembic env.py helper


# ---------------------------------------------------------------------------
# 2. FastAPI dependency injection functions (used as Depends() arguments)
# ---------------------------------------------------------------------------
def get_library_service():
    pass  # FastAPI Depends()


def get_analytics_service():
    pass  # FastAPI Depends()


def get_calibration_service():
    pass  # FastAPI Depends()


def get_config_service():
    pass  # FastAPI Depends()


def get_navidrome_service():
    pass  # FastAPI Depends()


def get_ml_service():
    pass  # FastAPI Depends()


def get_tagging_service():
    pass  # FastAPI Depends()


def get_pipeline_service():
    pass  # FastAPI Depends()


def get_info_service():
    pass  # FastAPI Depends()


def get_metadata_service():
    pass  # FastAPI Depends()


def get_file_watcher_service():
    pass  # FastAPI Depends()


def get_playlist_import_service():
    pass  # FastAPI Depends()


def get_vector_search_service():
    pass  # FastAPI Depends()


def get_vector_maintenance_service():
    pass  # FastAPI Depends()


def get_workers_coordinator():
    pass  # FastAPI Depends()


def get_key_service():
    pass  # FastAPI Depends() (auth.py)


# ---------------------------------------------------------------------------
# 3. FastAPI route handlers (web_* functions, called by router decorators)
# ---------------------------------------------------------------------------
def web_admin_restart():
    pass  # FastAPI route handler


def web_analytics_collection_overview():
    pass  # FastAPI route handler


def web_analytics_mood_analysis():
    pass  # FastAPI route handler


def web_analytics_mood_distribution():
    pass  # FastAPI route handler


def web_analytics_tag_co_occurrences():
    pass  # FastAPI route handler


def web_analytics_tag_correlations():
    pass  # FastAPI route handler


def web_analytics_tag_frequencies():
    pass  # FastAPI route handler


def web_convert_playlist():
    pass  # FastAPI route handler


def web_generate_personal_playlists():
    pass  # FastAPI route handler


def web_gpu_health():
    pass  # FastAPI route handler


def web_health():
    pass  # FastAPI route handler


def web_info():
    pass  # FastAPI route handler


def web_library_stats():
    pass  # FastAPI route handler


def web_navidrome_config():
    pass  # FastAPI route handler


def web_navidrome_playlist_generate():
    pass  # FastAPI route handler


def web_navidrome_playlist_preview():
    pass  # FastAPI route handler


def web_navidrome_preview():
    pass  # FastAPI route handler


def web_navidrome_push_playlist():
    pass  # FastAPI route handler


def web_navidrome_static_playlist():
    pass  # FastAPI route handler


def web_navidrome_sync_songs():
    pass  # FastAPI route handler


def web_navidrome_tag_values():
    pass  # FastAPI route handler


def web_navidrome_templates_generate():
    pass  # FastAPI route handler


def web_navidrome_templates_list():
    pass  # FastAPI route handler


def web_recent_activity():
    pass  # FastAPI route handler


def web_remove_tags():
    pass  # FastAPI route handler


def web_show_tags():
    pass  # FastAPI route handler


def web_spotify_credentials_status():
    pass  # FastAPI route handler


def web_work_status():
    pass  # FastAPI route handler


# ---------------------------------------------------------------------------
# 4. VRAM worker entry points (called by worker processes)
# ---------------------------------------------------------------------------
def register_vram_promise():
    pass  # Worker process entry point


def release_vram_promise():
    pass  # Worker process entry point


def count_vram_promises():
    pass  # Worker coordination


def acquire():
    pass  # VRAM promise acquisition


def probe():
    pass  # VRAM probe entry point


def _promise_key():
    pass  # Internal VRAM helper


# ---------------------------------------------------------------------------
# 5. Pydantic Settings attributes (accessed via model_dump(), dict(), etc.)
# ---------------------------------------------------------------------------
# These are Pydantic model fields that vulture sees as "unused attributes"
# but are actually serialized via model_dump() or accessed dynamically.
library_auto_tag = None  # Pydantic Settings field
library_ignore_patterns = None  # Pydantic Settings field
library_scan_poll_interval = None  # Pydantic Settings field
admin_password = None  # Pydantic Settings field
log_severity_level = None  # ONNX SessionOptions field
intra_op_num_threads = None  # ONNX SessionOptions field
inter_op_num_threads = None  # ONNX SessionOptions field
nomarr_identity_tag = None  # Logging context field
nomarr_role_tag = None  # Logging context field
context_str = None  # Logging context field
_echo = None  # Database engine field
ml_capacity = None  # Database adapter property


# ---------------------------------------------------------------------------
# 6. TypedDict/dataclass result types (used in type position)
# ---------------------------------------------------------------------------
class AggResult:
    pass  # TypedDict result type


class CalibrationStateDict:
    pass  # TypedDict result type


class GenerateCalibrationResult:
    pass  # TypedDict result type


class HistogramCalibrationResult:
    pass  # TypedDict result type


class SyncSongsResponse:
    pass  # TypedDict result type


class TokenizedGroup:
    pass  # TypedDict result type


class WorkerEnabledResult:
    pass  # TypedDict result type


class WorkerStatusResult:
    pass  # TypedDict result type


# ---------------------------------------------------------------------------
# 7. Component public API functions (imported by services/workflows)
# ---------------------------------------------------------------------------
# These are functions in _comp.py files that are part of the component public API.
# They are imported by services and workflows but vulture can't always trace the imports.


# Analytics components
def get_all_workers():
    pass  # Health check component


def get_component():
    pass  # Health check component


# Library components
def add_file():
    pass  # Library file mutation


def add_folder():
    pass  # Library folder mutation


def apply_detected_moves():
    pass  # Move detection


def bootstrap_states():
    pass  # File state initialization


def cancel_scan():
    pass  # Scan control


def clear_all_states():
    pass  # File state management


def clear_all_states_batch():
    pass  # File state management


def create_tag():
    pass  # Tag management


def delete_library_file():
    pass  # File deletion


def delete_tag():
    pass  # Tag management


def detect_file_moves():
    pass  # Move detection


def detect_file_move_via_db():
    pass  # Move detection


def detect_missing_files():
    pass  # Missing file detection


def detect_nd_path_prefix():
    pass  # Navidrome path detection


def file_has_tagged_state():
    pass  # File state check


def get_file_by_normalized_path():
    pass  # File lookup


def get_file_modified_times():
    pass  # File metadata


def get_files_by_chromaprint():
    pass  # Audio fingerprinting


def get_files_for_folders():
    pass  # Folder file listing


def get_files_for_tag():
    pass  # Tag file listing


def get_folder_by_path():
    pass  # Folder lookup


def get_root_folders():
    pass  # Root folder listing


def get_tag_by_name():
    pass  # Tag lookup


def get_tagged_library_paths():
    pass  # Tag path retrieval


def get_tag_value_frequencies():
    pass  # Tag statistics


def initialize_file_states():
    pass  # File state initialization


def list_directory():
    pass  # Directory listing


def mark_file_errored():
    pass  # Error state management


def normalize_album():
    pass  # Album normalization


def plan_full_scan():
    pass  # Scan planning


def plan_incremental_scan():
    pass  # Scan planning


def replace_file_states():
    pass  # State replacement


def scan_library_full():
    pass  # Full scan


def scan_library_quick():
    pass  # Quick scan


def tag_file():
    pass  # File tagging


def update_library_file_scan_metadata():
    pass  # Scan metadata update


def upsert_batch():
    pass  # Batch upsert


def upsert_file():
    pass  # File upsert


def write_library_tags():
    pass  # Tag writing


# ML components
def build_cold_vector_index():
    pass  # Vector index building


def clear_worker_context():
    pass  # Worker context cleanup


def compute_segment_stats():
    pass  # Segment statistics


def count_cold_embeddings():
    pass  # Embedding counting


def drop_cold_vector_index():
    pass  # Vector index cleanup


def filter_configured_heads():
    pass  # Head configuration


def get_default_histogram_spec():
    pass  # Histogram specification


def get_embedding_output_node():
    pass  # ONNX model inspection


def get_embedding_stream_for_file():
    pass  # Embedding stream


def get_enabled_models():
    pass  # Model listing


def get_generation_error():
    pass  # Generation error retrieval


def get_generation_result():
    pass  # Generation result retrieval


def has_embedding_index():
    pass  # Index existence check


def list_embedding_streams_by_backbone():
    pass  # Stream listing


def list_models_by_ids():
    pass  # Model listing


def ml_get_model_outputs():
    pass  # Model output retrieval


def ml_list_models():
    pass  # Model listing


def ml_mark_model_configured():
    pass  # Model configuration


def ml_trigger_vram_probe():
    pass  # VRAM probe trigger


def ml_update_output_label():
    pass  # Output label update


def promote_vectors():
    pass  # Vector promotion


def rebuild_backbone_embedding_index():
    pass  # Index rebuild


def rebuild_cold_vector_index():
    pass  # Cold index rebuild


def reconstruct_head_outputs_from_stats():
    pass  # Output reconstruction


def remove_embedding_streams_for_file():
    pass  # Stream removal


def remove_model_output():
    pass  # Output removal


def remove_output_streams_for_file():
    pass  # Stream removal


def replace_embedding_stream_for_file():
    pass  # Stream replacement


def score_segments():
    pass  # Segment scoring


def segment_waveform():
    pass  # Waveform segmentation


def verify_hot_empty():
    pass  # VRAM verification


# Calibration components
def compare_calibrations():
    pass  # Calibration comparison


def count_calibration_history():
    pass  # History counting


def create_calibration_history_snapshot():
    pass  # History snapshot


def delete_calibration_state():
    pass  # State deletion


def delete_old_calibration_history_snapshots():
    pass  # History cleanup


def export_calibration_state_to_json():
    pass  # State export


def get_all_calibration_histograms():
    pass  # Histogram retrieval


def get_apply_calibration_status():
    pass  # Calibration status


def get_calibration_state():
    pass  # State retrieval


def get_histogram_calibration_status():
    pass  # Histogram status


def get_histogram_for_head():
    pass  # Head histogram


def get_latest_calibration_history_snapshot():
    pass  # Latest snapshot


def import_calibration_state_from_json():
    pass  # State import


def remove_calibration_history_for_model():
    pass  # History removal


def start_apply_calibration():
    pass  # Calibration application


# Metadata components
def hydrate_song_with_tags():
    pass  # Song hydration


# Navidrome components
def navidrome_generate_playlists():
    pass  # Playlist generation


def navidrome_ping():
    pass  # Navidrome health check


def navidrome_similar_tracks():
    pass  # Similar tracks


def navidrome_status():
    pass  # Navidrome status


# Pipeline components
def backfill_vector_genres_workflow():
    pass  # Genre backfill


def get_library_pipeline_status():
    pass  # Pipeline status


def get_library_vector_stats():
    pass  # Vector statistics


def get_vector_stats():
    pass  # Vector statistics


# Playlist components
def create_or_replace_playlist():
    pass  # Playlist creation


def get_playlists():
    pass  # Playlist listing


# Tag components
def add_song_tag():
    pass  # Tag addition


def assign_tag_to_file():
    pass  # Tag assignment


def delete_song_tags():
    pass  # Tag deletion


def get_nomarr_tags_bulk():
    pass  # Bulk tag retrieval


def show_multiple():
    pass  # Multi-tag display


# Worker components
def cleanup_completed_tasks():
    pass  # Task cleanup


def cleanup_expired_sessions():
    pass  # Session cleanup


def disable_worker_system():
    pass  # Worker system control


def enable_worker_system():
    pass  # Worker system control


def get_session():
    pass  # Session retrieval


def list_tasks():
    pass  # Task listing


def login():
    pass  # Worker authentication


def logout():
    pass  # Worker logout


def recover_stale_heartbeats():
    pass  # Heartbeat recovery


# ---------------------------------------------------------------------------
# 8. Event handlers and magic methods
# ---------------------------------------------------------------------------
def on_any_event():
    pass  # Watchdog event handler


def __getattr__(name: str):
    pass  # Magic method for dynamic attribute access


# ---------------------------------------------------------------------------
# 9. Helper functions (used by other modules)
# ---------------------------------------------------------------------------
def decode_library_id():
    pass  # ID decoding


def get_component_ids():
    pass  # Component ID retrieval


def get_info():
    pass  # Info retrieval


def get_resource_status():
    pass  # Resource status


def get_scan_history():
    pass  # Scan history


def get_state_edges_for_files():
    pass  # State edge retrieval


def get_tier_description():
    pass  # Tier description


def get_values():
    pass  # Value retrieval


def has_key():
    pass  # Key existence check


def has_name():
    pass  # Name existence check


def has_value():
    pass  # Value existence check


def health_check():
    pass  # Health check


def infer_write_mode_from_tags():
    pass  # Write mode inference


def is_deezer_url():
    pass  # URL validation


def is_library_root_configured():
    pass  # Configuration check


def is_spotify_url():
    pass  # URL validation


def load_calibrations_cached_wf():
    pass  # Calibration loading


def read_nomarr_namespace():
    pass  # Namespace reading


def run_pending_migrations():
    pass  # Migration runner


def serve_dashboard():
    pass  # Dashboard serving


def serve_spa():
    pass  # SPA serving


def switch_watch_mode():
    pass  # Watch mode switching


def update_config():
    pass  # Config update


def update_pipeline_state():
    pass  # Pipeline state update


def update_songs():
    pass  # Song update


def update_write_mode():
    pass  # Write mode update


def validate_library_config():
    pass  # Config validation


# ---------------------------------------------------------------------------
# 10. Internal helper functions (prefixed with _)
# ---------------------------------------------------------------------------
def _as_float_list():
    pass  # Type conversion helper


def _assignment_row_to_dto():
    pass  # DTO conversion


def _compare_calibrations():
    pass  # Calibration comparison


def _folder_doc_id():
    pass  # Document ID helper


def _get_first():
    pass  # List helper


def _hydrate_file_with_tags():
    pass  # Tag hydration


def _interleave_per_cluster():
    pass  # Cluster interleaving


def _library_id_from_file_doc():
    pass  # ID extraction


def _normalize_file_id():
    pass  # ID normalization


def _scan_doc_id():
    pass  # Scan document ID


def _state_row_to_dto():
    pass  # DTO conversion


def _stream_key():
    pass  # Stream key


def _tags_for_file():
    pass  # Tag retrieval


def _tokenize_query():
    pass  # Query tokenization


# ---------------------------------------------------------------------------
# 11. Unused variables (local variables that are assigned but not used)
# ---------------------------------------------------------------------------
# These are typically intermediate calculations or loop variables.
# They are often false positives from complex data transformations.
# Adding them here prevents vulture from flagging them.

# Note: Variables are harder to allowlist than functions/classes.
# Vulture's allowlist format is designed for names, not local variables.
# For variables, we rely on the fact that they are local scope and
# vulture will only flag them if they are truly unused in their scope.
# Most "unused variable" findings are legitimate warnings about dead code.


# ---------------------------------------------------------------------------
# 12. Classes that are used but flagged as unused
# ---------------------------------------------------------------------------
class HealthComp:
    pass  # Health check component class


class _LibrarySnapshot:
    pass  # Internal snapshot class


# ---------------------------------------------------------------------------
# 13. Additional TypedDict fields and dataclass attributes
# ---------------------------------------------------------------------------
# These are fields in TypedDict or dataclass definitions that vulture
# sees as "unused variables" but are part of the data structure.
action_required = None  # TypedDict field
affected_file_count = None  # TypedDict field
all_matches = None  # TypedDict field
allow_short = None  # TypedDict field
ambiguous_matches = None  # TypedDict field
applied_at = None  # TypedDict field
artist_distribution = None  # TypedDict field
auto_curate = None  # TypedDict field
auto_tag = None  # TypedDict field
avg_tags_per_file = None  # TypedDict field
avg_track_length_ms = None  # TypedDict field
backbone_cache_size = None  # TypedDict field
completed_files = None  # TypedDict field
completed_heads = None  # TypedDict field
complete_files = None  # TypedDict field
current_file = None  # TypedDict field
current_head = None  # TypedDict field
current_head_index = None  # TypedDict field
deleted_files = None  # TypedDict field
disc_number = None  # TypedDict field
display_name = None  # TypedDict field
done = None  # TypedDict field
emb_graph = None  # TypedDict field
emit_all_scores = None  # TypedDict field
EncodedId = None  # TypedDict field
end_pos = None  # TypedDict field
entities = None  # TypedDict field
EQ = None  # TypedDict field
expires_in = None  # TypedDict field
files_checked = None  # TypedDict field
files_found = None  # TypedDict field
files_moved_count = None  # TypedDict field
files_repaired = None  # TypedDict field
FilterDict = None  # TypedDict field
finished_at = None  # TypedDict field
generated_at_ms = None  # TypedDict field
head_cache_size = None  # TypedDict field
head_index = None  # TypedDict field
head_name = None  # TypedDict field
histogram = None  # TypedDict field
is_nomarr_tag = None  # TypedDict field
is_running = None  # TypedDict field
last_modified = None  # TypedDict field
last_scan_at = None  # TypedDict field
library_id = None  # TypedDict field
max_classes = None  # TypedDict field
missing_files = None  # TypedDict field
model_id = None  # TypedDict field
model_name = None  # TypedDict field
new_files = None  # TypedDict field
new_path = None  # TypedDict field
old_duration = None  # TypedDict field
old_path = None  # TypedDict field
output_label = None  # TypedDict field
output_node = None  # TypedDict field
path_prefix = None  # TypedDict field
pipeline_id = None  # TypedDict field
playlist_id = None  # TypedDict field
playlist_name = None  # TypedDict field
promise_id = None  # TypedDict field
queue_size = None  # TypedDict field
scan_id = None  # TypedDict field
scan_type = None  # TypedDict field
song_id = None  # TypedDict field
start_pos = None  # TypedDict field
state = None  # TypedDict field
status_code = None  # TypedDict field
tag_count = None  # TypedDict field
tag_id = None  # TypedDict field
tag_name = None  # TypedDict field
task_id = None  # TypedDict field
top_ratio = None  # TypedDict field
total_files = None  # TypedDict field
total_files_to_scan = None  # TypedDict field
track_number = None  # TypedDict field
updated_files = None  # TypedDict field
vector_count = None  # TypedDict field
worker_id = None  # TypedDict field
year_distribution = None  # TypedDict field
genre_distribution = None  # TypedDict field
