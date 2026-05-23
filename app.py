import json
import logging
import socket
import time
from html import escape
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
    detections = camera.get("object_detections") or []
    detection_chips = "".join(
        f'<span class="chip">{escape(str(detection.get("label", "object")))} <b>{escape(str(detection.get("confidence", "")))}</b></span>'
        for detection in detections[:6]
    )
    if not detection_chips:
        detection_chips = '<span class="chip muted">No objects</span>'
    image_html = ""
    if image:
        image_html = (
            f'<div class="frame-wrap"><img src="{image}?api_key={api_key}&t={time.time()}" '
            f'alt="Latest frame for {escape(str(camera.get("camera_id", "camera")))}" /></div>'
        )
    return f"""
    <article class="camera">
      <div class="row">
        <div>
          <h2>{escape(str(camera.get("camera_id", "Unknown camera")))}</h2>
          <small>{escape(str(camera.get("worker_id", "unassigned")))}</small>
        </div>
        <span class="pill">{escape(str(camera.get("camera_status", "unknown")))}</span>
      </div>
      <div class="camera-metrics">
        <div><span>Frames</span><strong>{escape(str(camera.get("frame_count", 0)))}</strong></div>
        <div><span>Objects</span><strong>{escape(str(camera.get("object_count", len(detections))))}</strong></div>
        <div><span>Reconnects</span><strong>{escape(str(camera.get("reconnect_count", 0)))}</strong></div>
      </div>
      <div class="chips">{detection_chips}</div>
      <p class="summary">{escape(str(camera.get("ai_summary", "Waiting for AI analysis...")))}</p>
      {image_html}
      <footer>Updated {escape(str(camera.get("last_updated", "waiting")))}</footer>
    </article>
    """


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> str:
    api_key = request.query_params.get("api_key", "")
    status = collect_status()
    object_count = sum(int(camera.get("object_count", len(camera.get("object_detections", [])))) for camera in status["camera_status"])
    cameras = status["camera_status"] or [
        {"camera_id": camera_id, "camera_status": "waiting_for_worker", "worker_id": worker_id}
        for camera_id, worker_id in status["assignments"].items()
    ]
    worker_rows = "".join(
        f"<tr><td>{escape(str(worker.get('worker_id')))}</td><td><span class=\"table-pill\">{escape(str(worker.get('status')))}</span></td><td>{len(worker.get('active_cameras', []))}</td><td>{escape(str(worker.get('frame_count', 0)))}</td><td>{escape(str(worker.get('reconnect_count', 0)))}</td></tr>"
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
        * {{ box-sizing: border-box; }}
        body {{ margin: 0; background: #090d12; color: #f7fbff; font-family: Inter, Arial, sans-serif; }}
        body::before {{ content: ""; position: fixed; inset: 0; pointer-events: none; background: radial-gradient(circle at 25% 0%, rgba(39, 172, 142, .18), transparent 30%), radial-gradient(circle at 85% 10%, rgba(73, 144, 226, .16), transparent 26%); }}
        header {{ position: relative; padding: 26px 32px; border-bottom: 1px solid #22303b; background: rgba(14, 20, 27, .92); backdrop-filter: blur(12px); }}
        h1 {{ margin: 0 0 8px; font-size: 30px; letter-spacing: 0; }}
        header div {{ color: #9fb0bf; }}
        main {{ position: relative; padding: 24px 32px 34px; display: grid; gap: 22px; }}
        .metrics, .cameras {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; }}
        .metric, .camera, table {{ background: linear-gradient(180deg, rgba(25, 34, 43, .98), rgba(16, 23, 31, .98)); border: 1px solid #2d3d4d; border-radius: 8px; box-shadow: 0 16px 36px rgba(0, 0, 0, .26); }}
        .metric {{ padding: 17px; position: relative; overflow: hidden; }}
        .metric::after {{ content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 3px; background: linear-gradient(90deg, #30d19d, #52a8ff); }}
        .metric span, .camera-metrics span {{ color: #9fb0bf; font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }}
        .metric strong {{ display: block; font-size: 25px; margin-top: 7px; }}
        .camera {{ padding: 16px; display: grid; gap: 13px; }}
        .row {{ display: flex; justify-content: space-between; align-items: start; gap: 12px; }}
        h2 {{ margin: 0; font-size: 18px; }}
        small {{ color: #9fb0bf; display: block; margin-top: 4px; }}
        .pill, .table-pill {{ background: #123328; color: #82f0b6; border: 1px solid #236248; border-radius: 999px; padding: 5px 10px; font-size: 12px; white-space: nowrap; }}
        .camera-metrics {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }}
        .camera-metrics div {{ background: #0e151d; border: 1px solid #263645; border-radius: 8px; padding: 10px; min-width: 0; }}
        .camera-metrics strong {{ display: block; margin-top: 4px; font-size: 18px; }}
        .chips {{ display: flex; flex-wrap: wrap; gap: 8px; min-height: 28px; }}
        .chip {{ color: #dff7ff; background: #173047; border: 1px solid #2c5b7a; border-radius: 999px; padding: 6px 10px; font-size: 12px; }}
        .chip b {{ color: #8ee6ff; font-weight: 700; }}
        .chip.muted {{ color: #99a8b8; background: #121923; border-color: #2a3643; }}
        .summary {{ background: #0d141b; border-left: 3px solid #30d19d; padding: 12px; min-height: 44px; margin: 0; color: #d6e2eb; }}
        .frame-wrap {{ border-radius: 8px; overflow: hidden; border: 1px solid #2b3d4f; background: #05080c; }}
        img {{ width: 100%; display: block; aspect-ratio: 16 / 9; object-fit: cover; }}
        footer {{ color: #8597a8; font-size: 12px; }}
        table {{ width: 100%; border-collapse: collapse; overflow: hidden; }}
        th, td {{ text-align: left; padding: 12px; border-bottom: 1px solid #2b3846; }}
        th {{ color: #9fb0bf; font-weight: 700; font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }}
        section h2 {{ margin: 0 0 12px; }}
        @media (max-width: 720px) {{ header, main {{ padding-left: 16px; padding-right: 16px; }} .camera-metrics {{ grid-template-columns: 1fr; }} }}
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
          <div class="metric"><span>Objects detected</span><strong>{object_count}</strong></div>
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
