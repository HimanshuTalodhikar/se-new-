# AI Surveillance Dashboard Test Case Documentation

## 1. Purpose

This document gives a software tester a ready-to-run test plan for the distributed AI surveillance system. It covers Docker startup, dashboard access, camera stream processing, person detection, load balancing, Kafka events, camera discovery, reconnect behavior, API security, and shutdown/recovery.

## 2. Application Under Test

Project: Distributed AI Home Surveillance System

Main services:

| Service | Purpose |
|---|---|
| `dashboard` | FastAPI dashboard and API status view |
| `load-balancer` | Worker registration, camera assignment, health, discovery coordination |
| `worker1`, `worker2`, `worker3` | Camera stream readers, person detection, AI summary generation |
| `kafka-consumer` | Event consumer and monitoring logger |
| `kafka` | Event broker |
| `zookeeper` | Kafka coordination |

Main URLs:

| Target | URL |
|---|---|
| Dashboard UI | `http://127.0.0.1:8000/?api_key=change-me` |
| Dashboard health | `http://127.0.0.1:8000/health` |
| Dashboard status API | `http://127.0.0.1:8000/api/status?api_key=change-me` |
| Kafka host port | `127.0.0.1:9092` |

## 3. Prerequisites

Required:

- Docker Desktop running
- Docker Compose v2
- Project images already pulled or buildable
- At least one reachable IP/mobile camera stream
- `.env` configured

Optional:

- Ollama running on host for AI summaries
- `jq` installed for readable API output

Verify tools:

```bash
docker --version
docker compose version
jq --version
```

Verify Ollama if AI is enabled:

```bash
ollama list
curl http://127.0.0.1:11434/api/tags
```

## 4. Test Environment Setup

Go to the project:

```bash
cd /Users/himanshu/Desktop/docker-camera-wsl
```

Create `.env` if missing:

```bash
cp .env.example .env
```

Minimum `.env` values to check:

```env
DASHBOARD_API_KEY=change-me
CAMERAS={"camera1":"http://YOUR_CAMERA_IP:8080/video"}
OBJECT_DETECTION_ENABLED=true
OBJECT_DETECTION_BACKEND=auto
AI_ENABLED=true
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=phi3:mini
```

Start full system:

```bash
docker compose up -d --build
```

Check containers:

```bash
docker compose ps
```

Expected:

- `surveillance-dashboard` is `Up`
- `surveillance-load-balancer` is `Up`
- `surveillance-worker1`, `surveillance-worker2`, `surveillance-worker3` are `Up`
- `surveillance-kafka` is `Up`
- `surveillance-zookeeper` is `Up`

Open dashboard:

```text
http://127.0.0.1:8000/?api_key=change-me
```

## 5. Useful Tester Commands

View all logs:

```bash
docker compose logs -f
```

View dashboard logs:

```bash
docker compose logs -f dashboard
```

View worker logs:

```bash
docker compose logs -f worker1 worker2 worker3
```

View load balancer logs:

```bash
docker compose logs -f load-balancer
```

View Kafka consumer logs:

```bash
docker compose logs -f kafka-consumer
```

Check dashboard health:

```bash
curl -s http://127.0.0.1:8000/health | jq
```

Check dashboard status:

```bash
curl -s "http://127.0.0.1:8000/api/status?api_key=change-me" | jq
```

Check unauthorized API behavior:

```bash
curl -i http://127.0.0.1:8000/api/status
```

Check latest camera runtime files:

```bash
ls -la runtime
for f in runtime/camera_*.json; do echo "$f"; jq . "$f"; done
```

Check latest generated frames:

```bash
ls -lh detections
```

Restart only workers:

```bash
docker compose up -d --build worker1 worker2 worker3
```

Restart dashboard:

```bash
docker compose up -d --build dashboard
```

Stop all services:

```bash
docker compose down
```

Clean orphan containers if Docker warns about them:

```bash
docker compose down --remove-orphans
docker compose up -d --build
```

## 6. Test Data

Use at least these camera scenarios:

| Test Feed | Description |
|---|---|
| Person visible | A person clearly visible in frame |
| No person | Empty room, ceiling, table, monitor, wall, or floor only |
| Close-up person | Face/upper body close to camera |
| Sideways person | Phone/camera rotated 90 degrees |
| Unreachable camera | Invalid IP or stopped mobile camera app |
| Multiple cameras | Two or more valid camera URLs |

Suggested temporary `.env` examples:

Single valid camera:

```env
CAMERAS={"camera1":"http://YOUR_CAMERA_IP:8080/video"}
```

Two cameras:

```env
CAMERAS={"camera1":"http://CAMERA_1_IP:8080/video","camera2":"http://CAMERA_2_IP:8080/video"}
```

One valid and one invalid camera:

```env
CAMERAS={"camera1":"http://VALID_CAMERA_IP:8080/video","bad_camera":"http://192.0.2.10:8080/video"}
```

After `.env` changes:

```bash
docker compose up -d --build
```

## 7. Test Cases

### TC-001: Full Docker Startup

Objective: Verify all services start successfully.

Steps:

```bash
cd /Users/himanshu/Desktop/docker-camera-wsl
docker compose up -d --build
docker compose ps
```

Expected result:

- All required services are `Up`.
- Dashboard is available at `http://127.0.0.1:8000/?api_key=change-me`.

### TC-002: Dashboard Loads With Valid API Key

Objective: Verify UI loads when authorized.

Steps:

Open:

```text
http://127.0.0.1:8000/?api_key=change-me
```

Expected result:

- Page title shows `AI Surveillance Dashboard`.
- Metrics cards are visible.
- Camera cards are visible.
- Worker Utilization table is visible.

### TC-003: Dashboard Rejects Missing API Key

Objective: Verify API protection.

Steps:

```bash
curl -i http://127.0.0.1:8000/api/status
```

Expected result:

- Response status is `401 Unauthorized`.
- Body contains `{"detail":"Unauthorized"}`.

### TC-004: Health Endpoint Is Public

Objective: Verify `/health` works without API key.

Steps:

```bash
curl -s http://127.0.0.1:8000/health | jq
```

Expected result:

- JSON response contains `status: healthy`.
- Response includes `camera_status`, `worker_status`, `kafka_status`, `active_workers`.

### TC-005: Status API Returns Runtime Data

Objective: Verify authenticated runtime API.

Steps:

```bash
curl -s "http://127.0.0.1:8000/api/status?api_key=change-me" | jq
```

Expected result:

- JSON contains `dashboard`, `camera_status`, `worker_status`, `load_balancer`, `assignments`, `kafka`.

### TC-006: Worker Registration

Objective: Verify workers register with load balancer.

Steps:

```bash
docker compose logs --tail=100 load-balancer
curl -s http://127.0.0.1:8000/health | jq '.active_workers,.worker_status'
```

Expected result:

- Load balancer logs show `POST /register`.
- `active_workers` is greater than `0`.
- Worker status entries exist.

### TC-007: Camera Assignment

Objective: Verify cameras are assigned to workers.

Steps:

```bash
cat runtime/assignments.json | jq
```

Expected result:

- `assignments` contains camera IDs mapped to worker IDs.
- `cameras` contains configured camera URL map.

### TC-008: Valid Camera Connects

Objective: Verify a reachable camera stream connects.

Steps:

```bash
docker compose logs -f worker1 worker2 worker3
```

Watch dashboard camera card.

Expected result:

- Worker log shows `Camera connected`.
- Camera card status becomes `connected`.
- Frame count increases.
- `detections/<camera_id>_raw_latest.jpg` exists.
- `detections/<camera_id>_latest.jpg` exists.

### TC-009: Invalid Camera Shows Connection Failed

Objective: Verify reconnect/failure behavior.

Steps:

Set `.env`:

```env
CAMERAS={"bad_camera":"http://192.0.2.10:8080/video"}
```

Restart:

```bash
docker compose up -d --build
docker compose logs -f worker1 worker2 worker3
```

Expected result:

- Worker logs show `Camera connection failed`.
- Dashboard camera card status shows `connection_failed`.
- Reconnect count increases.

### TC-010: Person Detection Positive

Objective: Verify a visible person is detected.

Steps:

1. Point camera at a person.
2. Wait at least 10 seconds.
3. Run:

```bash
curl -s "http://127.0.0.1:8000/api/status?api_key=change-me" | jq '.camera_status[] | {camera_id, camera_status, object_count, object_detections, ai_summary}'
```

Expected result:

- Relevant camera has `object_count` greater than `0`.
- `object_detections[].label` is `person`.
- Annotated image displays green person bounding box.
- AI summary says `Person detected...` or `<N> persons detected...`.

### TC-011: Person Detection Negative

Objective: Verify empty feed does not show fake persons.

Steps:

1. Point camera at ceiling, wall, empty table, monitor, or empty room.
2. Wait at least 10 seconds.
3. Run:

```bash
curl -s "http://127.0.0.1:8000/api/status?api_key=change-me" | jq '.camera_status[] | {camera_id, object_count, object_detections, ai_summary}'
```

Expected result:

- `object_count` is `0`.
- `object_detections` is empty.
- Summary says `No person detected...` or waits for analysis if no frame was processed yet.

### TC-012: Close-Up Person Detection

Objective: Verify face/upper-body fallback detects close people.

Steps:

1. Put face or upper body close to camera.
2. Wait at least 10 seconds.
3. Check:

```bash
curl -s "http://127.0.0.1:8000/api/status?api_key=change-me" | jq '.camera_status[] | {camera_id, object_count, object_detections}'
```

Expected result:

- Person is detected.
- Detection count should be reasonable; one visible person should generally produce `object_count: 1`.

### TC-013: Rotated/Sideways Camera Feed

Objective: Verify sideways person detection.

Steps:

1. Rotate phone/camera 90 degrees.
2. Show one person.
3. Wait at least 10 seconds.
4. Check dashboard and API.

Command:

```bash
curl -s "http://127.0.0.1:8000/api/status?api_key=change-me" | jq '.camera_status[] | {camera_id, object_count, object_detections}'
```

Expected result:

- Person is detected in sideways feed.
- No obvious duplicate count for a single person.

### TC-014: Duplicate Detection Control

Objective: Verify one person is not counted as multiple persons due to overlapping boxes.

Steps:

1. Show one person in the feed.
2. Wait for annotated frame to update.
3. Open dashboard.
4. Check chips under camera card and API.

Command:

```bash
curl -s "http://127.0.0.1:8000/api/status?api_key=change-me" | jq '.camera_status[] | {camera_id, object_count, object_detections}'
```

Expected result:

- One visible person should normally show `object_count: 1`.
- No large false box should cover unrelated background areas such as windows, ceiling, table, or monitor.

### TC-015: Latest Frame Files Are Written

Objective: Verify workers write raw and annotated frames.

Steps:

```bash
ls -lh detections
```

Expected result:

- For connected cameras:
  - `<camera_id>_raw_latest.jpg` exists.
  - `<camera_id>_latest.jpg` exists.
- Annotated frame updates over time when feed is active.

### TC-016: Click To Expand Frame

Objective: Verify full-frame viewer.

Steps:

1. Open dashboard.
2. Click `Expand` on a camera frame.
3. Press `Escape` or click `Close`.

Expected result:

- Modal opens with full camera frame.
- Modal closes with `Escape` or `Close`.

### TC-017: Kafka Online Status

Objective: Verify Kafka is reachable.

Steps:

```bash
docker compose ps kafka zookeeper
curl -s "http://127.0.0.1:8000/api/status?api_key=change-me" | jq '.kafka'
```

Expected result:

- Kafka and Zookeeper are `Up`.
- Dashboard API shows Kafka connected/online.

### TC-018: Kafka Event Publishing

Objective: Verify worker events are published and consumed.

Steps:

```bash
docker compose logs -f kafka-consumer
```

Expected result:

- Consumer logs show camera events or monitoring data after workers process frames.

### TC-019: AI Summary With Ollama Available

Objective: Verify local AI summary integration.

Steps:

```bash
curl http://127.0.0.1:11434/api/tags
docker compose logs -f worker1 worker2 worker3
```

Show a person in camera.

Expected result:

- Worker does not repeatedly log Ollama failures.
- Summary is grounded:
  - `Person detected on <camera_id>; review the live feed.`
  - `<N> persons detected on <camera_id>; review the live feed.`
  - `No person detected on <camera_id>.`

### TC-020: AI Summary When Ollama Is Unavailable

Objective: Verify graceful fallback.

Steps:

1. Stop Ollama on host or set invalid Ollama URL in `.env`.
2. Restart workers:

```bash
docker compose up -d --build worker1 worker2 worker3
docker compose logs -f worker1 worker2 worker3
```

Expected result:

- Worker logs Ollama warning.
- App continues processing frames.
- Summary uses local fallback such as `Ollama unavailable; detected <N> person(s).`

### TC-021: Worker Restart Recovery

Objective: Verify system recovers after worker restart.

Steps:

```bash
docker compose restart worker1
sleep 10
docker compose ps
curl -s "http://127.0.0.1:8000/api/status?api_key=change-me" | jq '.active_workers,.assignments'
```

Expected result:

- Worker returns to `Up`.
- Load balancer receives heartbeat.
- Assignments remain valid or rebalance.

### TC-022: Worker Failure Reassignment

Objective: Verify load balancer marks stale worker unhealthy and reassigns cameras.

Steps:

```bash
docker compose stop worker1
sleep 25
curl -s "http://127.0.0.1:8000/api/status?api_key=change-me" | jq '.worker_status,.assignments'
docker compose start worker1
```

Expected result:

- Stopped worker becomes unhealthy or inactive.
- Cameras assigned to healthy workers.
- Worker can rejoin after restart.

### TC-023: Dashboard Responsive Layout

Objective: Verify UI does not overlap on smaller screens.

Steps:

1. Open dashboard in browser.
2. Resize window to desktop, tablet, and mobile widths.
3. Observe camera cards and metrics.

Expected result:

- Desktop uses multiple columns.
- Narrow screens stack cards.
- Text and status pills do not overlap.
- No horizontal page scroll from camera cards.

### TC-024: Camera Auto Discovery Disabled

Objective: Verify discovery disabled state.

Steps:

Set `.env`:

```env
ENABLE_CAMERA_DISCOVERY=false
```

Restart:

```bash
docker compose up -d --build
curl -s "http://127.0.0.1:8000/api/status?api_key=change-me" | jq '.discovery'
```

Expected result:

- Discovery reports disabled.
- Manual `CAMERAS` configuration is still used.

### TC-025: Camera Auto Discovery Enabled

Objective: Verify discovery can scan configured subnet and preserve manual cameras.

Steps:

Set `.env`:

```env
ENABLE_CAMERA_DISCOVERY=true
CAMERA_DISCOVERY_SUBNETS=192.168.1.0/24
```

Replace subnet with tester network.

Restart and inspect:

```bash
docker compose up -d --build
docker compose logs -f load-balancer
cat runtime/camera_registry.json | jq
curl -s "http://127.0.0.1:8000/api/status?api_key=change-me" | jq '.discovery,.camera_registry'
```

Expected result:

- Discovery scans private subnet.
- Valid streams are written to `runtime/camera_registry.json`.
- Manual cameras remain configured.
- Discovered camera cards appear if valid streams exist.

### TC-026: Discovery Rejects Unsafe Public Subnet By Default

Objective: Verify discovery safety guard.

Steps:

Set `.env`:

```env
ENABLE_CAMERA_DISCOVERY=true
CAMERA_DISCOVERY_SUBNETS=8.8.8.0/24
CAMERA_DISCOVERY_ALLOW_PUBLIC_LAN=false
```

Restart:

```bash
docker compose up -d --build
docker compose logs --tail=100 load-balancer
```

Expected result:

- Discovery does not scan public subnet.
- Logs indicate subnet is blocked/skipped or discovery fails safely.

### TC-027: Runtime Files Persist Through Restart

Objective: Verify shared runtime/detection volumes work.

Steps:

```bash
ls -la runtime detections
docker compose restart dashboard
sleep 5
ls -la runtime detections
```

Expected result:

- Runtime and detection files remain on host.
- Dashboard can read existing status after restart.

### TC-028: Log Format

Objective: Verify structured logging exists.

Steps:

```bash
docker compose logs --tail=50 dashboard
docker compose logs --tail=50 worker1
```

Expected result:

- App logs are structured JSON or readable service logs.
- Errors include useful fields such as camera ID or path.

### TC-029: Stop System

Objective: Verify clean shutdown.

Steps:

```bash
docker compose down
docker compose ps
```

Expected result:

- Compose services stop.
- No project containers remain running except unrelated orphan containers.

### TC-030: Rebuild From Clean State

Objective: Verify fresh rebuild works.

Steps:

```bash
docker compose down --remove-orphans
docker compose build --no-cache
docker compose up -d
docker compose ps
```

Expected result:

- Images rebuild successfully.
- Services start successfully.
- Dashboard loads.

## 8. Regression Checklist

Run this quick checklist after any code change:

```bash
cd /Users/himanshu/Desktop/docker-camera-wsl
python3 -m py_compile app.py load_balancer.py worker.py object_detector.py config.py camera_discovery.py
docker compose up -d --build
docker compose ps
curl -s http://127.0.0.1:8000/health | jq
curl -s "http://127.0.0.1:8000/api/status?api_key=change-me" | jq '.active_workers,.frame_count,.reconnect_count,.kafka'
docker compose logs --tail=80 worker1 worker2 worker3
```

Expected:

- Python compile has no errors.
- Services are up.
- Health API responds.
- Dashboard API responds with valid JSON.
- Worker logs do not show repeated crashes.

## 9. Defect Reporting Template

Use this format for bugs:

```text
Title:
Environment:
Docker command used:
.env camera config:
Steps to reproduce:
Expected result:
Actual result:
Screenshot/video:
Relevant command output:
Relevant logs:
```

Collect logs:

```bash
docker compose ps
docker compose logs --tail=200 dashboard > dashboard.log
docker compose logs --tail=200 load-balancer > load-balancer.log
docker compose logs --tail=300 worker1 worker2 worker3 > workers.log
curl -s "http://127.0.0.1:8000/api/status?api_key=change-me" | jq > status.json
```

## 10. Known Notes For Testers

- If camera cards show `connection_failed`, the detector cannot run until the stream is reachable.
- If the phone camera app sleeps or changes IP, update `CAMERAS` in `.env` and restart Compose.
- If Docker warns about orphan containers, run `docker compose down --remove-orphans`.
- AI summaries depend on Ollama unless fallback is triggered.
- Person detection is tuned for security-style person presence, not identity recognition.
- The dashboard API requires `api_key` except `/health`.
