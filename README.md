# Distributed AI Home Surveillance System

This project is a production-style distributed home surveillance system built with Python, OpenCV, FastAPI, Docker Compose, Kafka, and local Ollama AI.

The original project was a single-container camera dashboard. It has been upgraded into a multi-service architecture with stream-level load balancing, worker isolation, person-only detection, local AI summaries, health monitoring, WSL-aware networking, and Kafka-based async event processing.

## What We Built

The system now supports:

- IP/mobile camera streaming with OpenCV
- multiple cameras
- custom stream-level load balancing
- multiple worker containers
- person-only home security detection
- rotated camera/person detection support
- annotated latest frames
- click-to-zoom full-frame image viewer
- local Ollama AI summaries using `phi3:mini`
- Kafka event publishing
- FastAPI dashboard
- API-key protected dashboard
- health monitoring
- auto reconnect
- structured JSON logs
- suspicious access logging
- Docker Compose deployment
- Windows, WSL2, Linux, and macOS networking support

## Current Architecture

```text
Camera Registry
        |
Cross-Platform Network Manager
        |
Custom Load Balancer
        |
Worker Containers
worker1, worker2, worker3
        |
Person Detection + Ollama AI Summary
        |
Kafka Event Pipeline
        |
Dashboard + Monitoring
```

## Service Overview

| Service | File | Responsibility |
|---|---|---|
| `dashboard` | `app.py` | FastAPI dashboard, API auth, health endpoint, UI, latest frame display |
| `load-balancer` | `load_balancer.py` | Worker registration, camera assignment, worker heartbeat, reassignment |
| `worker1/2/3` | `worker.py` | Camera reading, reconnects, frame sampling, person detection, Ollama summaries, Kafka publishing |
| `kafka-consumer` | `kafka_consumer.py` | Consumes Kafka events and logs monitoring data |
| `kafka` | Docker image | Async event broker |
| `zookeeper` | Docker image | Kafka coordination |

## Main Features

### 1. Multi-Camera Streaming

Cameras are configured using the `CAMERAS` environment variable as a JSON map:

```env
CAMERAS={"camera1":"http://192.0.0.4:8080/video","camera2":"http://192.0.0.5:8080/video"}
```

Each camera has a stable ID. Workers process entire camera streams, not individual frames.

### 2. Custom Load Balancer

The load balancer assigns whole camera streams to workers using deterministic hashing:

```text
hash(camera_id) % number_of_healthy_workers
```

This avoids frame-level shuffling and keeps camera state isolated inside one worker.

The load balancer supports:

- worker registration
- worker heartbeat
- dynamic worker health tracking
- camera-to-worker assignment
- camera reassignment when workers become unhealthy
- `/health` reporting

### 3. Worker Containers

Each worker:

- receives assigned cameras from the load balancer
- opens camera streams with OpenCV
- reconnects automatically if a camera fails
- processes frames at a configurable rate
- drops stale frames under overload
- saves raw and annotated latest frames
- detects persons only
- asks Ollama for a short local AI summary
- publishes metadata to Kafka
- writes runtime status for the dashboard

### 4. Person-Only Detection

This is now tuned for home security. The system ignores non-security objects like tables, chairs, bottles, TVs, dogs, and background objects.

Detection behavior:

- only `person` detections are accepted
- non-person DNN classes are filtered out
- fallback detector also detects people only
- duplicate person boxes are suppressed with NMS
- person boxes are padded slightly to cover more of the visible body
- suspicious full-frame false-positive boxes are rejected
- rotated detection is supported for sideways camera feeds

Useful settings:

```env
OBJECT_DETECTION_ENABLED=true
OBJECT_DETECTION_BACKEND=auto
OBJECT_CONFIDENCE_THRESHOLD=0.45
PERSON_NMS_THRESHOLD=0.35
PERSON_BOX_PADDING=0.08
PERSON_MAX_AREA_RATIO=0.85
PERSON_ROTATION_DETECTION=true
```

The detector uses OpenCV DNN with MobileNet-SSD and caches model files in `models/`.

### 5. Local Ollama AI

Gemini has been removed. The project now uses local Ollama running on your PC.

Default model:

```env
OLLAMA_MODEL=phi3:mini
```

Default Docker-to-host URL:

```env
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

Workers call:

```text
POST /api/generate
```

The prompt is intentionally constrained for home security. The system also applies a grounding guard so the final dashboard summary is based only on detected person count.

Example summaries:

```text
Person detected on camera1; review the live feed.
No person detected on camera2.
2 persons detected on camera1; review the live feed.
```

This prevents the model from inventing unsupported details such as time, intent, gender, identity, suspicious behavior, or threat level.

### 6. Kafka Event Pipeline

Workers publish events to Kafka topics:

- `camera-events`
- `ai-analysis-events`
- `system-health-events`

Example event:

```json
{
  "camera_id": "camera1",
  "worker_id": "worker1",
  "timestamp": "2026-05-23T12:00:00Z",
  "frame_id": 300,
  "camera_status": "connected",
  "ai_summary": "Person detected on camera1; review the live feed.",
  "frame_path": "/detections/camera1_latest.jpg",
  "raw_frame_path": "/detections/camera1_raw_latest.jpg",
  "object_count": 1,
  "object_detections": [
    {
      "label": "person",
      "confidence": 0.984,
      "box": {"x": 610, "y": 0, "width": 1061, "height": 1079}
    }
  ]
}
```

Kafka allows monitoring, analytics, and downstream consumers to run asynchronously without blocking camera processing.

### 7. Dashboard

The dashboard is served by FastAPI at:

```text
http://127.0.0.1:8000/?api_key=change-me
```

It shows:

- active workers
- total frames
- persons detected
- reconnect count
- Kafka status
- all cameras
- assigned worker per camera
- camera health
- frame count
- person count
- latest AI summary
- latest annotated frame
- worker utilization

Image behavior:

- preview uses `object-fit: contain`
- image is not cropped
- clicking the image opens a full-frame zoom modal
- Escape or Close exits the modal

### 8. Security

Security features added:

- dashboard is API-key protected
- unauthorized users receive HTTP 401
- dashboard binds to localhost only:

```yaml
127.0.0.1:8000:8000
```

- request logging
- suspicious non-local access logging
- no cloud AI key required
- `.env` is ignored by Git
- camera authentication supports URLs like:

```text
http://user:password@camera-ip/video
```

or:

```env
CAMERA_AUTH_JSON={"camera1":{"username":"user","password":"password"}}
```

### 9. Stability

Stability features:

- camera auto reconnect
- worker heartbeat
- worker stale detection
- camera reassignment on worker failure
- graceful shutdown
- Docker restart policy:

```yaml
restart: unless-stopped
```

- Ollama retry logic
- fallback local summary if Ollama is unavailable
- structured JSON logs
- health endpoints

### 10. Scalability

The system is designed for horizontal scaling.

Scalable design choices:

- stream-level load balancing
- worker isolation
- async Kafka events
- frame dropping under overload
- configurable FPS
- configurable frame sampling
- shared event contract
- dashboard reads runtime status without blocking workers

For larger deployments, run more worker containers with unique `WORKER_ID` values and connect them to the same load balancer and Kafka broker.

## Cross-Platform And WSL Support

`network_manager.py` detects the runtime environment with Python `platform`.

Behavior:

- Windows/WSL2 local host streams can use `host.docker.internal`
- Linux/macOS can use direct camera LAN IPs
- camera auth can be injected consistently

Important settings:

```env
HOST_OS=auto
WSL_USE_HOST_DOCKER_INTERNAL=true
```

For LAN cameras, direct IP URLs are preferred.

## API Endpoints

### Dashboard

```http
GET /
```

Requires API key using either:

```http
X-API-Key: change-me
```

or:

```text
?api_key=change-me
```

### Dashboard Status API

```http
GET /api/status
```

Returns aggregate dashboard, camera, worker, Kafka, and assignment status.

### Dashboard Health

```http
GET /health
```

Public health endpoint. Returns:

- camera status
- worker status
- Kafka status
- frame count
- uptime
- reconnect count
- active workers

### Load Balancer

```http
POST /register
POST /heartbeat
GET /assignments/{worker_id}
GET /health
```

The load balancer is internal to Docker Compose and is not exposed publicly.

## Environment Variables

Core:

| Variable | Default | Purpose |
|---|---|---|
| `DASHBOARD_API_KEY` | `change-me` | Dashboard/API auth key |
| `CAMERAS` | camera JSON | Camera registry |
| `CAMERA_AUTH_JSON` | `{}` | Optional camera credentials |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

Ollama:

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Ollama API URL from Docker |
| `OLLAMA_MODEL` | `phi3:mini` | Local Ollama model |
| `AI_ENABLED` | `true` | Enables AI summaries |
| `AI_MAX_WORDS` | `22` | Summary length guard |
| `AI_RETRIES` | `3` | Ollama retry count |
| `AI_MIN_INTERVAL_SECONDS` | `0` | Delay between AI calls per camera |
| `AI_ERROR_BACKOFF_SECONDS` | `120` | Cooldown after Ollama errors |

Person detection:

| Variable | Default | Purpose |
|---|---|---|
| `OBJECT_DETECTION_ENABLED` | `true` | Enables person detection |
| `OBJECT_DETECTION_BACKEND` | `auto` | `auto`, `dnn`, or `opencv` |
| `OBJECT_CONFIDENCE_THRESHOLD` | `0.45` | Minimum person confidence |
| `PERSON_NMS_THRESHOLD` | `0.35` | Duplicate box suppression |
| `PERSON_BOX_PADDING` | `0.08` | Box expansion ratio |
| `PERSON_MAX_AREA_RATIO` | `0.85` | Rejects huge false boxes |
| `PERSON_ROTATION_DETECTION` | `true` | Checks rotated orientations |

Performance:

| Variable | Default | Purpose |
|---|---|---|
| `PROCESS_EVERY_N_FRAMES` | `30` | Analyze every Nth frame |
| `TARGET_FPS` | `8` | Camera read throttle |
| `FRAME_QUEUE_SIZE` | `2` | Stale frame drop buffer |

Networking:

| Variable | Default | Purpose |
|---|---|---|
| `HOST_OS` | `auto` | Platform detection override |
| `WSL_USE_HOST_DOCKER_INTERNAL` | `true` | WSL/Windows host URL rewrite |

Kafka:

| Variable | Default |
|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | `kafka:9092` |
| `KAFKA_CAMERA_EVENTS_TOPIC` | `camera-events` |
| `KAFKA_AI_EVENTS_TOPIC` | `ai-analysis-events` |
| `KAFKA_HEALTH_EVENTS_TOPIC` | `system-health-events` |

## How To Run

### 1. Start Ollama On The Host

Make sure Ollama is installed and running on your PC.

Verify the model exists:

```bash
ollama list
```

Expected model:

```text
phi3:mini
```

Test Ollama:

```bash
curl http://127.0.0.1:11434/api/tags
```

### 2. Configure The Project

```bash
cp .env.example .env
```

Edit `.env`:

```env
DASHBOARD_API_KEY=change-me
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=phi3:mini
CAMERAS={"camera1":"http://YOUR_CAMERA_IP:8080/video"}
```

### 3. Start Docker Compose

```bash
docker compose up --build
```

Or detached:

```bash
docker compose up -d --build
```

### 4. Open Dashboard

```text
http://127.0.0.1:8000/?api_key=change-me
```

## Useful Commands

View containers:

```bash
docker compose ps
```

View worker logs:

```bash
docker compose logs -f worker1 worker2 worker3
```

View dashboard logs:

```bash
docker compose logs -f dashboard
```

Restart workers:

```bash
docker compose up -d --build worker1 worker2 worker3
```

Stop everything:

```bash
docker compose down
```

Test Ollama from a worker container:

```bash
docker compose run --rm --no-deps worker1 python - <<'PY'
import requests
response = requests.post(
    "http://host.docker.internal:11434/api/generate",
    json={"model": "phi3:mini", "prompt": "Reply with: ok", "stream": False},
    timeout=60,
)
print(response.status_code)
print(response.json().get("response"))
PY
```

## Troubleshooting

### Dashboard Shows Unauthorized

Use the API key:

```text
http://127.0.0.1:8000/?api_key=change-me
```

If you changed `DASHBOARD_API_KEY`, use your new value.

### Camera Shows `connection_failed`

Check:

- phone/IP camera app is running
- camera URL is correct
- phone and computer are on the same network
- Docker can reach the camera IP
- WSL/Windows URL rewriting is configured correctly

Check logs:

```bash
docker compose logs -f worker1 worker2 worker3
```

### Ollama Unavailable

Check host Ollama:

```bash
curl http://127.0.0.1:11434/api/tags
```

Check from Docker:

```bash
docker compose run --rm --no-deps worker1 curl http://host.docker.internal:11434/api/tags
```

If Docker cannot reach Ollama, keep Ollama running on the host and use:

```env
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

### Bad Person Boxes

Tune:

```env
OBJECT_CONFIDENCE_THRESHOLD=0.50
PERSON_NMS_THRESHOLD=0.30
PERSON_BOX_PADDING=0.05
PERSON_MAX_AREA_RATIO=0.75
PERSON_ROTATION_DETECTION=true
```

Then restart:

```bash
docker compose up -d --build worker1 worker2 worker3
```

### Docker Pull Timeout

Kafka/Zookeeper images can be large. Retry:

```bash
COMPOSE_PARALLEL_LIMIT=1 docker compose pull zookeeper
COMPOSE_PARALLEL_LIMIT=1 docker compose pull kafka
```

Then:

```bash
docker compose up --build
```

## What Changed From The Original App

Original:

- one `app.py`
- one container
- one camera URL
- direct Gemini call
- simple dashboard
- no load balancing
- no Kafka
- limited health reporting

Current:

- multi-service Docker Compose architecture
- dashboard service separated from camera processing
- load balancer service
- multiple worker containers
- Kafka async event pipeline
- local Ollama AI instead of Gemini
- person-only detection
- WSL-aware network manager
- API-key security
- structured logs
- full health endpoint
- latest raw and annotated frames
- full-frame click zoom
- horizontal scaling pattern

## Interview Talking Points

This project demonstrates:

- distributed system decomposition
- stream-level load balancing
- worker isolation
- async event-driven design with Kafka
- Dockerized deployment
- local AI integration with Ollama
- computer vision pipeline using OpenCV
- home-security-focused person detection
- fault tolerance through reconnects and health checks
- cross-platform networking awareness
- API security and monitoring

## Branch

Active development branch:

```text
codex/distributed-surveillance
```
