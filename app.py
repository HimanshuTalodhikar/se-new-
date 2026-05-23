import json
import logging
import socket
import time
from pathlib import Path
from typing import Any

import requests
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import settings
from logging_config import configure_logging

configure_logging()
logger = logging.getLogger("dashboard")
started_at = time.time()

app = FastAPI(title="AI Surveillance Dashboard")
app.mount("/detections", StaticFiles(directory=str(settings.detections_dir)), name="detections")


def _is_authorized(request: Request) -> bool:
    supplied = request.headers.get("x-api-key") or request.query_params.get("api_key")
    return bool(settings.dashboard_api_key) and supplied == settings.dashboard_api_key


def _remote_is_local(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost"} or host.startswith("172.") or host.startswith("10.")


@app.middleware("http")
async def security_and_request_logging(request: Request, call_next):
    request_start = time.time()
    public_path = request.url.path == "/health"
    authorized = public_path or _is_authorized(request)

    if not authorized:
        logger.warning(
            "Unauthorized dashboard access",
            extra={"_path": request.url.path, "_remote_addr": request.client.host if request.client else "unknown"},
        )
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    if not _remote_is_local(request):
        logger.warning(
            "Suspicious non-local access",
            extra={"_path": request.url.path, "_remote_addr": request.client.host if request.client else "unknown"},
        )

    response = await call_next(request)
    logger.info(
        "Request completed",
        extra={
            "_method": request.method,
            "_path": request.url.path,
            "_status_code": response.status_code,
            "_duration_ms": round((time.time() - request_start) * 1000, 2),
        },
    )
    return response


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _kafka_status() -> dict[str, Any]:
    if not settings.kafka_enabled:
        return {"enabled": False, "connected": False}
    host, _, port = settings.kafka_bootstrap_servers.partition(":")
    try:
        with socket.create_connection((host, int(port or "9092")), timeout=1):
            return {"enabled": True, "connected": True, "bootstrap_servers": settings.kafka_bootstrap_servers}
    except OSError as exc:
        return {"enabled": True, "connected": False, "bootstrap_servers": settings.kafka_bootstrap_servers, "last_error": str(exc)}


def _load_balancer_health() -> dict[str, Any]:
    try:
        response = requests.get(f"{settings.load_balancer_url}/health", timeout=2)
        if response.ok:
            return response.json()
    except requests.RequestException as exc:
        return {"status": "unavailable", "error": str(exc)}
    return {"status": "unavailable"}


def collect_status() -> dict[str, Any]:
    camera_files = sorted(settings.runtime_dir.glob("camera_*.json"))
    worker_files = sorted(settings.runtime_dir.glob("worker_*.json"))
    cameras = [_read_json(path, {}) for path in camera_files]
    workers = [_read_json(path, {}) for path in worker_files]
    load_balancer = _load_balancer_health()
    assignments = _read_json(settings.runtime_dir / "assignments.json", {})
    return {
        "dashboard": {"status": "healthy", "uptime": round(time.time() - started_at, 2)},
        "camera_status": cameras,
        "worker_status": workers,
        "load_balancer": load_balancer,
        "assignments": assignments.get("assignments", load_balancer.get("assignments", {})),
        "kafka": _kafka_status(),
        "frame_count": sum(int(camera.get("frame_count", 0)) for camera in cameras),
        "reconnect_count": sum(int(camera.get("reconnect_count", 0)) for camera in cameras),
        "active_workers": load_balancer.get("active_workers", len(workers)),
    }


@app.get("/health")
def health() -> dict[str, Any]:
    status = collect_status()
    return {
        "status": "healthy",
        "camera_status": status["camera_status"],
        "worker_status": status["worker_status"],
        "kafka_status": status["kafka"],
        "frame_count": status["frame_count"],
        "uptime": status["dashboard"]["uptime"],
        "reconnect_count": status["reconnect_count"],
        "active_workers": status["active_workers"],
    }


@app.get("/api/status")
def api_status() -> dict[str, Any]:
    return collect_status()


def _camera_card(camera: dict[str, Any], api_key: str) -> str:
    image = camera.get("latest_frame") or ""
    image_html = ""
    if image:
        image_html = f'<img src="{image}?api_key={api_key}&t={time.time()}" alt="Latest frame for {camera.get("camera_id", "camera")}" />'
    return f"""
    <article class="camera">
      <div class="row">
        <h2>{camera.get("camera_id", "Unknown camera")}</h2>
        <span class="pill">{camera.get("camera_status", "unknown")}</span>
      </div>
      <div class="grid">
        <span>Worker</span><strong>{camera.get("worker_id", "unassigned")}</strong>
        <span>Frames</span><strong>{camera.get("frame_count", 0)}</strong>
        <span>Reconnects</span><strong>{camera.get("reconnect_count", 0)}</strong>
        <span>Updated</span><strong>{camera.get("last_updated", "waiting")}</strong>
      </div>
      <p class="summary">{camera.get("ai_summary", "Waiting for AI analysis...")}</p>
      {image_html}
    </article>
    """


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> str:
    api_key = request.query_params.get("api_key", "")
    status = collect_status()
    cameras = status["camera_status"] or [
        {"camera_id": camera_id, "camera_status": "waiting_for_worker", "worker_id": worker_id}
        for camera_id, worker_id in status["assignments"].items()
    ]
    worker_rows = "".join(
        f"<tr><td>{worker.get('worker_id')}</td><td>{worker.get('status')}</td><td>{len(worker.get('active_cameras', []))}</td><td>{worker.get('frame_count', 0)}</td><td>{worker.get('reconnect_count', 0)}</td></tr>"
        for worker in status["worker_status"]
    )
    camera_cards = "".join(_camera_card(camera, api_key) for camera in cameras)
    return f"""
    <!doctype html>
    <html>
    <head>
      <title>AI Surveillance Dashboard</title>
      <meta http-equiv="refresh" content="3">
      <style>
        body {{ margin: 0; background: #101418; color: #f8fafc; font-family: Arial, sans-serif; }}
        header {{ padding: 24px 32px; border-bottom: 1px solid #26313d; background: #151b22; }}
        h1 {{ margin: 0 0 8px; font-size: 28px; }}
        main {{ padding: 24px 32px; display: grid; gap: 20px; }}
        .metrics, .cameras {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; }}
        .metric, .camera, table {{ background: #18212b; border: 1px solid #2b3846; border-radius: 8px; padding: 16px; }}
        .metric span, .grid span {{ color: #9aa8b5; font-size: 13px; }}
        .metric strong {{ display: block; font-size: 24px; margin-top: 6px; }}
        .row {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; }}
        h2 {{ margin: 0; font-size: 18px; }}
        .pill {{ background: #16382a; color: #7ee2a8; border: 1px solid #245b42; border-radius: 999px; padding: 4px 10px; font-size: 12px; }}
        .grid {{ display: grid; grid-template-columns: 110px 1fr; gap: 8px; margin: 14px 0; }}
        .summary {{ background: #111820; border-left: 3px solid #55c2ff; padding: 12px; min-height: 44px; }}
        img {{ width: 100%; border-radius: 6px; border: 1px solid #2b3846; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ text-align: left; padding: 10px; border-bottom: 1px solid #2b3846; }}
        th {{ color: #9aa8b5; font-weight: 600; }}
      </style>
    </head>
    <body>
      <header>
        <h1>AI Surveillance Dashboard</h1>
        <div>Live distributed camera processing with worker assignment, Kafka events, and health monitoring.</div>
      </header>
      <main>
        <section class="metrics">
          <div class="metric"><span>Active workers</span><strong>{status["active_workers"]}</strong></div>
          <div class="metric"><span>Total frames</span><strong>{status["frame_count"]}</strong></div>
          <div class="metric"><span>Reconnects</span><strong>{status["reconnect_count"]}</strong></div>
          <div class="metric"><span>Kafka</span><strong>{ "Online" if status["kafka"].get("connected") else "Offline" }</strong></div>
        </section>
        <section class="cameras">{camera_cards}</section>
        <section>
          <h2>Worker Utilization</h2>
          <table>
            <thead><tr><th>Worker</th><th>Health</th><th>Camera Load</th><th>Frames</th><th>Reconnects</th></tr></thead>
            <tbody>{worker_rows or '<tr><td colspan="5">Waiting for workers...</td></tr>'}</tbody>
          </table>
        </section>
      </main>
    </body>
    </html>
    """


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
