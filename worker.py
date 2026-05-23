import json
import logging
import queue
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import requests

from config import settings
from kafka_producer import EventProducer
from logging_config import configure_logging
from network_manager import NetworkManager
from object_detector import ObjectDetector

configure_logging()
logger = logging.getLogger("worker")
producer = EventProducer()
shutdown_event = threading.Event()


class GeminiAnalyzer:
    """Gemini client with retries; disabled cleanly when no API key is configured."""

    def __init__(self) -> None:
        self.enabled = settings.ai_enabled and bool(settings.gemini_api_key)
        self.model = None
        self.last_analysis_at: dict[str, float] = {}
        self.unavailable_until = 0.0
        if self.enabled:
            import google.generativeai as genai

            genai.configure(api_key=settings.gemini_api_key)
            self.model = genai.GenerativeModel(settings.gemini_model)

    def analyze(self, camera_id: str, detections: list[dict[str, Any]]) -> str:
        if not self.enabled:
            return "AI analysis disabled or GEMINI_API_KEY not configured."

        now = time.time()
        if now < self.unavailable_until:
            return self._local_summary(detections, "Gemini quota cooldown active")
        if settings.ai_min_interval_seconds > 0 and now - self.last_analysis_at.get(camera_id, 0) < settings.ai_min_interval_seconds:
            return self._local_summary(detections, "Gemini throttled")

        labels = [detection.get("label", "object") for detection in detections]
        detection_summary = f"{len(labels)} person(s)" if labels else "no person detected"
        prompt = (
            "You are an AI surveillance assistant. Return exactly one short sentence, "
            f"maximum {settings.gemini_max_words} words. "
            f"Camera: {camera_id}. Person detection result: {detection_summary}. "
            "Mention only whether a person is visible and the key security observation."
        )
        for attempt in range(1, settings.gemini_retries + 1):
            try:
                response = self.model.generate_content(prompt)
                self.last_analysis_at[camera_id] = time.time()
                return self._shorten(getattr(response, "text", "") or "No AI summary returned.")
            except Exception as exc:
                error = str(exc)
                logger.warning("Gemini attempt failed", extra={"_camera_id": camera_id, "_attempt": attempt, "_error": error})
                if "429" in error or "quota" in error.lower():
                    self.unavailable_until = time.time() + settings.ai_quota_backoff_seconds
                    return self._local_summary(detections, "Gemini quota exceeded")
                time.sleep(min(2 * attempt, 10))
        return "Gemini analysis failed after retries."

    def _local_summary(self, detections: list[dict[str, Any]], reason: str) -> str:
        labels = [str(detection.get("label", "object")) for detection in detections]
        if labels:
            return f"{reason}; detected {len(labels)} person(s)."
        return f"{reason}; no person detected."

    def _shorten(self, text: str) -> str:
        words = text.strip().replace("\n", " ").split()
        if len(words) <= settings.gemini_max_words:
            return " ".join(words)
        return " ".join(words[: settings.gemini_max_words]).rstrip(".,;:") + "."


class CameraProcessor:
    """Owns one whole camera stream; load balancing never splits individual frames."""

    def __init__(self, camera_id: str, analyzer: GeminiAnalyzer) -> None:
        self.camera_id = camera_id
        self.analyzer = analyzer
        self.frame_count = 0
        self.saved_frame_count = 0
        self.reconnect_count = 0
        self.status = "starting"
        self.latest_frame = ""
        self.latest_raw_frame = ""
        self.ai_summary = "Waiting for AI analysis..."
        self.object_detections: list[dict[str, Any]] = []
        self.last_updated = ""
        self.stop_event = threading.Event()
        self.frame_queue: queue.Queue[Any] = queue.Queue(maxsize=settings.frame_queue_size)
        self.detector = ObjectDetector()
        self.thread = threading.Thread(target=self.run, daemon=True, name=f"camera-{camera_id}")

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=5)

    def snapshot(self) -> dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "worker_id": settings.worker_id,
            "camera_status": self.status,
            "frame_count": self.frame_count,
            "saved_frame_count": self.saved_frame_count,
            "reconnect_count": self.reconnect_count,
            "latest_frame": self.latest_frame,
            "latest_raw_frame": self.latest_raw_frame,
            "ai_summary": self.ai_summary,
            "object_detections": self.object_detections,
            "object_count": len(self.object_detections),
            "last_updated": self.last_updated,
        }

    def _write_status(self) -> None:
        path = settings.runtime_dir / f"camera_{self.camera_id}.json"
        path.write_text(json.dumps(self.snapshot(), indent=2), encoding="utf-8")

    def _save_frame(self, frame: Any) -> None:
        self.saved_frame_count += 1
        safe_camera_id = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in self.camera_id)
        raw_filename = f"{safe_camera_id}_raw_latest.jpg"
        annotated_filename = f"{safe_camera_id}_latest.jpg"
        raw_frame_path = settings.detections_dir / raw_filename
        annotated_frame_path = settings.detections_dir / annotated_filename
        cv2.imwrite(str(raw_frame_path), frame)
        if settings.object_detection_enabled:
            self.object_detections, annotated_frame = self.detector.detect(frame)
        else:
            self.object_detections, annotated_frame = [], frame
        cv2.imwrite(str(annotated_frame_path), annotated_frame)
        self.latest_raw_frame = f"/detections/{raw_filename}"
        self.latest_frame = f"/detections/{annotated_filename}"
        self.last_updated = datetime.now(timezone.utc).isoformat()

        if self.saved_frame_count % max(settings.ai_every_n_saved_frames, 1) == 0:
            self.ai_summary = self.analyzer.analyze(self.camera_id, self.object_detections)

        event = {
            "camera_id": self.camera_id,
            "worker_id": settings.worker_id,
            "timestamp": self.last_updated,
            "frame_id": self.frame_count,
            "camera_status": self.status,
            "ai_summary": self.ai_summary,
            "frame_path": self.latest_frame,
            "raw_frame_path": self.latest_raw_frame,
            "object_detections": self.object_detections,
            "object_count": len(self.object_detections),
            "reconnect_count": self.reconnect_count,
        }
        producer.publish(settings.camera_events_topic, event)
        if self.ai_summary:
            producer.publish(settings.ai_events_topic, event)
        self._write_status()

    def run(self) -> None:
        min_delay = 1.0 / max(settings.target_fps, 0.1)
        while not self.stop_event.is_set() and not shutdown_event.is_set():
            camera_url = NetworkManager.get_camera_url(self.camera_id)
            cap = cv2.VideoCapture(camera_url)
            if not cap.isOpened():
                self.status = "connection_failed"
                self.reconnect_count += 1
                self._write_status()
                logger.warning("Camera connection failed", extra={"_camera_id": self.camera_id})
                self.stop_event.wait(settings.reconnect_delay_seconds)
                continue

            self.status = "connected"
            logger.info("Camera connected", extra={"_camera_id": self.camera_id})
            last_frame_time = 0.0
            while not self.stop_event.is_set() and not shutdown_event.is_set():
                ok, frame = cap.read()
                if not ok:
                    self.status = "reconnecting"
                    self.reconnect_count += 1
                    self._write_status()
                    cap.release()
                    break

                now = time.time()
                if now - last_frame_time < min_delay:
                    continue
                last_frame_time = now
                self.frame_count += 1

                if self.frame_count % max(settings.process_every_n_frames, 1) == 0:
                    if self.frame_queue.full():
                        try:
                            self.frame_queue.get_nowait()
                        except queue.Empty:
                            pass
                    self.frame_queue.put_nowait(frame)
                    self._save_frame(self.frame_queue.get_nowait())

            self.stop_event.wait(settings.reconnect_delay_seconds)


class WorkerRuntime:
    def __init__(self) -> None:
        self.analyzer = GeminiAnalyzer()
        self.processors: dict[str, CameraProcessor] = {}
        self.started_at = time.time()

    def _request(self, method: str, path: str, **kwargs) -> requests.Response | None:
        try:
            return requests.request(method, f"{settings.load_balancer_url}{path}", timeout=5, **kwargs)
        except requests.RequestException as exc:
            logger.warning("Load balancer unavailable", extra={"_error": str(exc)})
            return None

    def register(self) -> None:
        payload = {"worker_id": settings.worker_id, "url": f"http://{settings.worker_id}:{settings.worker_port}", "capacity": 100}
        self._request("POST", "/register", json=payload)

    def sync_assignments(self) -> None:
        response = self._request("GET", f"/assignments/{settings.worker_id}")
        if not response or response.status_code >= 400:
            return
        assigned = set(response.json().get("cameras", []))
        current = set(self.processors)

        for camera_id in assigned - current:
            processor = CameraProcessor(camera_id, self.analyzer)
            self.processors[camera_id] = processor
            processor.start()
        for camera_id in current - assigned:
            self.processors[camera_id].stop()
            del self.processors[camera_id]

    def heartbeat(self) -> None:
        frame_count = sum(processor.frame_count for processor in self.processors.values())
        reconnect_count = sum(processor.reconnect_count for processor in self.processors.values())
        payload = {
            "worker_id": settings.worker_id,
            "frame_count": frame_count,
            "reconnect_count": reconnect_count,
            "active_cameras": list(self.processors),
            "status": "healthy",
        }
        self._request("POST", "/heartbeat", json=payload)
        worker_status = {
            **payload,
            "uptime": round(time.time() - self.started_at, 2),
            "camera_details": {camera_id: processor.snapshot() for camera_id, processor in self.processors.items()},
            "kafka": producer.status(),
            "network": NetworkManager.environment(),
        }
        (settings.runtime_dir / f"worker_{settings.worker_id}.json").write_text(json.dumps(worker_status, indent=2), encoding="utf-8")
        producer.publish(settings.health_events_topic, {"service": "worker", **worker_status})

    def run(self) -> None:
        while not shutdown_event.is_set():
            self.register()
            self.sync_assignments()
            self.heartbeat()
            shutdown_event.wait(settings.worker_heartbeat_interval)
        for processor in list(self.processors.values()):
            processor.stop()


def _stop(_signum, _frame) -> None:
    shutdown_event.set()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    settings.detections_dir.mkdir(parents=True, exist_ok=True)
    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    WorkerRuntime().run()
