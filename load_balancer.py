import hashlib
import json
import signal
import threading
import time
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from config import settings
from kafka_producer import EventProducer
from logging_config import configure_logging

configure_logging()

app = FastAPI(title="AI Surveillance Load Balancer")
producer = EventProducer()
started_at = time.time()
lock = threading.RLock()
shutdown_event = threading.Event()

workers: dict[str, dict[str, Any]] = {}
assignments: dict[str, str] = {}
camera_status: dict[str, dict[str, Any]] = {}


class WorkerRegistration(BaseModel):
    worker_id: str
    url: str | None = None
    capacity: int = 10


class WorkerHeartbeat(BaseModel):
    worker_id: str
    frame_count: int = 0
    reconnect_count: int = 0
    active_cameras: list[str] = []
    status: str = "healthy"


def _assignment_path() -> Path:
    return settings.runtime_dir / "assignments.json"


def _stable_index(camera_id: str, worker_count: int) -> int:
    digest = hashlib.sha256(camera_id.encode("utf-8")).hexdigest()
    return int(digest, 16) % worker_count


def _healthy_worker_ids() -> list[str]:
    now = time.time()
    return sorted(
        worker_id
        for worker_id, worker in workers.items()
        if worker.get("status") == "healthy" and now - worker.get("last_seen", 0) <= settings.worker_stale_after
    )


def _rebalance() -> None:
    healthy = _healthy_worker_ids()
    assignments.clear()
    if healthy:
        for camera_id in sorted(settings.cameras):
            assignments[camera_id] = healthy[_stable_index(camera_id, len(healthy))]
    payload = {
        "updated_at": time.time(),
        "cameras": settings.cameras,
        "workers": workers,
        "assignments": assignments,
        "camera_status": camera_status,
    }
    _assignment_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _watchdog() -> None:
    while not shutdown_event.is_set():
        with lock:
            now = time.time()
            changed = False
            for worker_id, worker in workers.items():
                if now - worker.get("last_seen", 0) > settings.worker_stale_after and worker.get("status") != "unhealthy":
                    worker["status"] = "unhealthy"
                    changed = True
            if changed:
                _rebalance()
            producer.publish(
                settings.health_events_topic,
                {
                    "service": "load-balancer",
                    "worker_status": workers,
                    "active_workers": len(_healthy_worker_ids()),
                    "camera_count": len(settings.cameras),
                    "uptime": round(now - started_at, 2),
                },
            )
        shutdown_event.wait(5)


@app.on_event("startup")
def startup() -> None:
    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=_watchdog, daemon=True, name="load-balancer-watchdog").start()


@app.on_event("shutdown")
def shutdown() -> None:
    shutdown_event.set()


@app.post("/register")
def register_worker(worker: WorkerRegistration) -> dict[str, Any]:
    with lock:
        workers[worker.worker_id] = {
            "worker_id": worker.worker_id,
            "url": worker.url,
            "capacity": worker.capacity,
            "status": "healthy",
            "last_seen": time.time(),
            "frame_count": 0,
            "reconnect_count": 0,
            "active_cameras": [],
        }
        _rebalance()
        return {"registered": True, "assignments": assignments}


@app.post("/heartbeat")
def heartbeat(heartbeat_data: WorkerHeartbeat) -> dict[str, Any]:
    with lock:
        worker = workers.setdefault(heartbeat_data.worker_id, {"worker_id": heartbeat_data.worker_id, "capacity": 10})
        worker.update(heartbeat_data.dict())
        worker["last_seen"] = time.time()
        worker["status"] = heartbeat_data.status
        for camera_id in heartbeat_data.active_cameras:
            camera_status.setdefault(camera_id, {})["worker_id"] = heartbeat_data.worker_id
            camera_status[camera_id]["last_seen"] = time.time()
        _rebalance()
        return {"ok": True, "assigned_cameras": [c for c, w in assignments.items() if w == heartbeat_data.worker_id]}


@app.get("/assignments/{worker_id}")
def get_worker_assignments(worker_id: str) -> dict[str, Any]:
    with lock:
        _rebalance()
        assigned = [camera_id for camera_id, assigned_worker in assignments.items() if assigned_worker == worker_id]
        return {"worker_id": worker_id, "cameras": assigned, "camera_urls": {camera_id: settings.cameras[camera_id] for camera_id in assigned}}


@app.get("/health")
def health() -> dict[str, Any]:
    with lock:
        _rebalance()
        return {
            "status": "healthy",
            "uptime": round(time.time() - started_at, 2),
            "camera_count": len(settings.cameras),
            "active_workers": len(_healthy_worker_ids()),
            "workers": workers,
            "assignments": assignments,
            "kafka": producer.status(),
        }


def _stop(_signum, _frame) -> None:
    shutdown_event.set()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    uvicorn.run(app, host="0.0.0.0", port=9000)
