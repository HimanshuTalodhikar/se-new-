# Distributed AI Surveillance System

This project upgrades the original single-container OpenCV + Gemini dashboard into a production-style distributed surveillance pipeline.

## Architecture

```text
Camera Registry
        |
Cross-Platform Network Layer
        |
Custom Load Balancer
        |
Worker Containers
worker1, worker2, workerN
        |
Kafka Event Pipeline
        |
Dashboard + Monitoring + AI Analytics
```

## Services

- `dashboard`: FastAPI dashboard on `127.0.0.1:8000`, protected by `DASHBOARD_API_KEY`.
- `load-balancer`: Assigns whole camera streams to healthy workers using `sha256(camera_id) % worker_count`.
- `worker1`, `worker2`, `worker3`: Independent OpenCV processing containers.
- `kafka`: Event broker for camera, AI, and health events.
- `zookeeper`: Kafka coordination service.
- `kafka-consumer`: Monitoring consumer that logs the event pipeline.

## Run

```bash
cp .env.example .env
docker compose up --build
```

Open the dashboard:

```text
http://127.0.0.1:8000/?api_key=change-me
```

Set a real dashboard key and Gemini key in `.env` for real deployments.

## Configuration

`config.py` reads all secrets and runtime settings from environment variables.

Important variables:

- `DASHBOARD_API_KEY`: API key required for dashboard and `/api/status`.
- `GEMINI_API_KEY`: Gemini key used by workers. No key disables AI gracefully.
- `CAMERAS`: JSON map of camera IDs to stream URLs.
- `CAMERA_AUTH_JSON`: Optional JSON auth map for cameras.
- `HOST_OS`: `auto`, `Windows`, `Linux`, or `Darwin`.
- `WSL_USE_HOST_DOCKER_INTERNAL`: Rewrites local Windows/WSL camera URLs to `host.docker.internal`.
- `PROCESS_EVERY_N_FRAMES`: Frame sampling interval.
- `TARGET_FPS`: Worker read throttle.
- `FRAME_QUEUE_SIZE`: Small queue used to drop stale frames during overload.
- `OBJECT_DETECTION_ENABLED`: Enables OpenCV object annotations on saved frames.
- `OBJECT_DETECTION_BACKEND`: `auto`, `dnn`, or `opencv`. `auto` uses OpenCV DNN and falls back to classical OpenCV detection.
- `OBJECT_CONFIDENCE_THRESHOLD`: Minimum DNN detection confidence.
- `GEMINI_MAX_WORDS`: Keeps Gemini summaries short for dashboard readability.
- `AI_MIN_INTERVAL_SECONDS`: Minimum delay between Gemini calls per camera.
- `AI_QUOTA_BACKOFF_SECONDS`: Cooldown after Gemini quota/rate-limit errors.

Camera auth can be embedded directly:

```text
http://user:password@192.168.1.50:8080/video
```

Or provided separately:

```json
{"camera1":{"username":"user","password":"password"}}
```

## Security

- Dashboard binds to localhost only: `127.0.0.1:8000:8000`.
- API-key middleware returns HTTP 401 for unauthorized dashboard access.
- Gemini keys are environment variables, not hardcoded source.
- Requests are logged as structured JSON.
- Suspicious non-local access attempts are logged.
- Camera credentials are supported through URL auth or `CAMERA_AUTH_JSON`.

## Stability

- Workers reconnect automatically when a camera disconnects.
- Gemini calls retry before returning a failure summary.
- Docker services use `restart: unless-stopped`.
- Load balancer marks workers unhealthy after missed heartbeats.
- Cameras are reassigned when a worker becomes unhealthy.
- Graceful shutdown stops camera threads and releases OpenCV captures.
- `/health` returns camera status, worker status, Kafka status, frame count, uptime, reconnect count, and active workers.

## Scalability

The load balancer assigns stream ownership, not individual frames. This keeps frame order and camera state isolated per worker while allowing horizontal scale-out by adding workers.

Scale workers:

```bash
docker compose up --build --scale worker1=1 --scale worker2=1 --scale worker3=1
```

For larger deployments, add more worker services or run the same worker image with unique `WORKER_ID` values. Kafka decouples frame metadata and AI results from dashboard rendering so monitoring consumers can scale independently.

Workers drop stale queued frames under overload instead of building unbounded memory pressure. Tune `TARGET_FPS`, `PROCESS_EVERY_N_FRAMES`, and `FRAME_QUEUE_SIZE` based on GPU/CPU/network capacity.

## Object Detection

Workers run object detection before publishing frame events. By default, the detector uses OpenCV DNN with MobileNet-SSD for general objects and falls back to lightweight classical OpenCV detection if the DNN model is unavailable.

OpenCV fallback includes:

- HOG people detection
- Haar face detection
- motion contour detection

Each saved frame produces an annotated latest image plus object metadata:

```json
{
  "object_count": 2,
  "object_detections": [
    {"label": "person", "confidence": 0.84},
    {"label": "motion", "confidence": 0.41}
  ]
}
```

The DNN model files are cached in `models/` and ignored by Git. For a heavier production deployment, `object_detector.py` can be swapped for YOLO, TensorRT, OpenVINO, or a cloud vision model while keeping the same worker/dashboard contract.

## WSL And Cross-Platform Networking

`network_manager.py` detects the runtime using Python `platform` plus WSL hints. On Linux/macOS it uses the configured camera URL directly. On Windows/WSL2, local host camera URLs such as `http://127.0.0.1:8080/video` are rewritten to `http://host.docker.internal:8080/video` so containers can reach streams hosted on Windows.

For LAN IP cameras, use their direct IP address in `CAMERAS`.

## Kafka Topics

Workers publish:

- `camera-events`
- `ai-analysis-events`
- `system-health-events`

Event shape:

```json
{
  "camera_id": "camera1",
  "worker_id": "worker1",
  "timestamp": "2026-05-23T12:00:00Z",
  "frame_id": 300,
  "camera_status": "connected",
  "ai_summary": "Short Gemini summary",
  "frame_path": "/detections/camera1_latest.jpg"
}
```

`kafka_consumer.py` consumes these topics and logs monitoring information.

## Dashboard

The dashboard shows:

- all cameras
- assigned worker
- object detection labels and counts
- latest AI summary
- frame count
- health status
- reconnect count
- Kafka status
- worker load and health
- latest frame
- annotated detection boxes

The page auto-refreshes every three seconds.
