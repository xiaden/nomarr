"""
Web package.
"""

# Import combined router for FastAPI app
from .analytics import (
    web_analytics_mood_distribution,
    web_analytics_tag_co_occurrences,
    web_analytics_tag_correlations,
    web_analytics_tag_frequencies,
)
from .auth import LoginRequest, LoginResponse, LogoutResponse, login, logout
from .calibration import (
    CalibrationRequest,
    apply_calibration_to_library,
    clear_calibration_queue,
    generate_calibration,
    get_calibration_status,
)
from .config import ConfigUpdateRequest, get_config, update_config
from .dependencies import (
    get_analytics_service,
    get_calibration_service,
    get_config,
    get_config_service,
    get_event_broker,
    get_library_service,
    get_ml_service,
    get_navidrome_service,
    get_processor_coordinator,
    get_queue_service,
    get_recalibration_service,
    get_worker_pool,
    get_worker_service,
)
from .info import web_health, web_info
from .library import web_library_stats
from .navidrome import (
    web_navidrome_config,
    web_navidrome_playlist_generate,
    web_navidrome_playlist_preview,
    web_navidrome_preview,
    web_navidrome_templates_generate,
    web_navidrome_templates_list,
)
from .processing import BatchProcessRequest, ProcessRequest, web_batch_process, web_list, web_process
from .queue import (
    AdminResetRequest,
    RemoveRequest,
    web_admin_cache_refresh,
    web_admin_cleanup,
    web_admin_clear_all,
    web_admin_clear_completed,
    web_admin_clear_errors,
    web_admin_flush,
    web_admin_remove,
    web_admin_reset,
    web_queue_depth,
    web_status,
)
from .router import router
from .sse import web_sse_status
from .tags import web_show_tags
from .worker import web_admin_restart, web_admin_worker_pause, web_admin_worker_resume

__all__ = [
    "AdminResetRequest",
    "BatchProcessRequest",
    "CalibrationRequest",
    "ConfigUpdateRequest",
    "LoginRequest",
    "LoginResponse",
    "LogoutResponse",
    "ProcessRequest",
    "RemoveRequest",
    "apply_calibration_to_library",
    "clear_calibration_queue",
    "generate_calibration",
    "get_analytics_service",
    "get_calibration_service",
    "get_calibration_status",
    "get_config",
    "get_config_service",
    "get_event_broker",
    "get_library_service",
    "get_ml_service",
    "get_navidrome_service",
    "get_processor_coordinator",
    "get_queue_service",
    "get_recalibration_service",
    "get_worker_pool",
    "get_worker_service",
    "login",
    "logout",
    "router",
    "update_config",
    "web_admin_cache_refresh",
    "web_admin_cleanup",
    "web_admin_clear_all",
    "web_admin_clear_completed",
    "web_admin_clear_errors",
    "web_admin_flush",
    "web_admin_remove",
    "web_admin_reset",
    "web_admin_restart",
    "web_admin_worker_pause",
    "web_admin_worker_resume",
    "web_analytics_mood_distribution",
    "web_analytics_tag_co_occurrences",
    "web_analytics_tag_correlations",
    "web_analytics_tag_frequencies",
    "web_batch_process",
    "web_health",
    "web_info",
    "web_library_stats",
    "web_list",
    "web_navidrome_config",
    "web_navidrome_playlist_generate",
    "web_navidrome_playlist_preview",
    "web_navidrome_preview",
    "web_navidrome_templates_generate",
    "web_navidrome_templates_list",
    "web_process",
    "web_queue_depth",
    "web_show_tags",
    "web_sse_status",
    "web_status",
]
