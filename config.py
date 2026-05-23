import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _json(name: str, default: Any) -> Any:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _parse_cameras() -> dict[str, str]:
    """Accept JSON maps/lists or a comma-separated camera id/url list."""
    raw = os.getenv("CAMERAS")
    if not raw:
        return {os.getenv("CAMERA_ID", "camera1"): os.getenv("CAMERA_URL", "http://192.0.0.4:8080/video")}

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items()}
        if isinstance(parsed, list):
            cameras: dict[str, str] = {}
            for index, item in enumerate(parsed, start=1):
                if isinstance(item, dict):
                    camera_id = str(item.get("id", f"camera{index}"))
                    cameras[camera_id] = str(item.get("url", ""))
                else:
                    cameras[f"camera{index}"] = str(item)
            return {k: v for k, v in cameras.items() if v}
    except json.JSONDecodeError:
        pass

    cameras = {}
    for index, url in enumerate(raw.split(","), start=1):
        clean_url = url.strip()
        if clean_url:
            cameras[f"camera{index}"] = clean_url
    return cameras or {"camera1": raw}


@dataclass(frozen=True)
class Settings:
    # Paths are shared by dashboard, workers, and the load balancer through Docker volumes.
    detections_dir: Path = Path(os.getenv("DETECTIONS_DIR", "detections"))
    runtime_dir: Path = Path(os.getenv("RUNTIME_DIR", "runtime"))

    # Security and external service secrets must come from environment variables.
    dashboard_api_key: str = os.getenv("DASHBOARD_API_KEY", "change-me")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    cameras: dict[str, str] = field(default_factory=_parse_cameras)
    camera_auth: dict[str, dict[str, str]] = field(default_factory=lambda: _json("CAMERA_AUTH_JSON", {}))

    load_balancer_url: str = os.getenv("LOAD_BALANCER_URL", "http://load-balancer:9000")
    worker_id: str = os.getenv("WORKER_ID", "worker-local")
    worker_port: int = _int("WORKER_PORT", 9100)
    worker_heartbeat_interval: float = _float("WORKER_HEARTBEAT_INTERVAL", 5.0)
    worker_stale_after: float = _float("WORKER_STALE_AFTER", 20.0)

    kafka_bootstrap_servers: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    kafka_enabled: bool = _bool("KAFKA_ENABLED", True)
    camera_events_topic: str = os.getenv("KAFKA_CAMERA_EVENTS_TOPIC", "camera-events")
    ai_events_topic: str = os.getenv("KAFKA_AI_EVENTS_TOPIC", "ai-analysis-events")
    health_events_topic: str = os.getenv("KAFKA_HEALTH_EVENTS_TOPIC", "system-health-events")

    process_every_n_frames: int = _int("PROCESS_EVERY_N_FRAMES", 30)
    target_fps: float = _float("TARGET_FPS", 8.0)
    ai_every_n_saved_frames: int = _int("AI_EVERY_N_SAVED_FRAMES", 1)
    ai_enabled: bool = _bool("AI_ENABLED", True)
    gemini_retries: int = _int("GEMINI_RETRIES", 3)
    gemini_max_words: int = _int("GEMINI_MAX_WORDS", 22)
    ai_min_interval_seconds: float = _float("AI_MIN_INTERVAL_SECONDS", 120.0)
    ai_quota_backoff_seconds: float = _float("AI_QUOTA_BACKOFF_SECONDS", 3600.0)
    object_detection_enabled: bool = _bool("OBJECT_DETECTION_ENABLED", True)
    object_detection_backend: str = os.getenv("OBJECT_DETECTION_BACKEND", "auto")
    object_confidence_threshold: float = _float("OBJECT_CONFIDENCE_THRESHOLD", 0.35)
    dnn_model_dir: Path = Path(os.getenv("DNN_MODEL_DIR", "models"))
    dnn_prototxt_url: str = os.getenv(
        "DNN_PROTOTXT_URL",
        "https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/deploy.prototxt",
    )
    dnn_model_url: str = os.getenv(
        "DNN_MODEL_URL",
        "https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/mobilenet_iter_73000.caffemodel",
    )
    reconnect_delay_seconds: float = _float("RECONNECT_DELAY_SECONDS", 5.0)
    frame_queue_size: int = _int("FRAME_QUEUE_SIZE", 2)

    host_os: str = os.getenv("HOST_OS", "auto")
    wsl_use_host_docker_internal: bool = _bool("WSL_USE_HOST_DOCKER_INTERNAL", True)
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
settings.detections_dir.mkdir(parents=True, exist_ok=True)
settings.runtime_dir.mkdir(parents=True, exist_ok=True)
settings.dnn_model_dir.mkdir(parents=True, exist_ok=True)
