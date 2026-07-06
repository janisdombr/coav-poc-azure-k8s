# coav-gui-backend — Java Spring Boot API

REST + WebSocket backend for the COAV GUI. Two runtime modes:

| Mode | Profile | Flight source | ISSR zones |
|---|---|---|---|
| **Mock** | `mock` | Built-in flight simulator (no Azure needed) | Dynamic — refreshed every 30 min from Open-Meteo |
| **Azure** (default) | *(none)* | Azure Event Hub `telemetry-adsb-inbound` | Dynamic — refreshed every 30 min from Open-Meteo |

> ISSR zones are always dynamic (real weather data from Open-Meteo, no API key needed).
> The `mock` profile only controls the **flight source**, not weather.

## Prerequisites

- **Docker Desktop** — for build and local run (Maven is NOT required; it runs inside the build container)
- **Maven** — only if you want to run tests locally: `brew install maven`
- **`kubectl` + `minikube`** — only for the *superseded* K8s deploy (see EXPERIMENT_HISTORY); not needed for local testing or the current cloud deploy

## API endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/flights` | Active flights updated in the last 5 min (JSON array, newest first). `alert` = `CRITICAL` / `APPROACHING` / null (pure ISSR geometry) |
| GET | `/api/issr-zones` | ISSR zone definitions (2 fallback or N dynamic from Open-Meteo) |
| GET | `/api/cameras` · `/api/camera-verification` | Decoupled ground-camera verification channel (camera-keyed) |
| GET/POST | `/api/advisory` · `/advisory/accept` · `/advisory/reject` | 3-tier ATC advisory workflow (FDO) |
| POST | `/api/correction` | Submit ATC flight level correction (OWASP A03 validated, rate-limited) |
| WS | `/ws` (STOMP) | Live updates → `/topic/flights` · `/advisories` · `/corrections` · `/cameras` |

Full API reference (payloads, flows) → [root README](../../README.md#api-reference).

---

## Local testing (no cluster required)

> **Important:** run these from the **project root** (`coav-poc-azure-k8s/`).
> Do **not** activate the minikube Docker context — use Docker Desktop.
> If you previously ran `eval $(minikube docker-env)`, reset it first:
> `eval $(minikube docker-env -u)`

### 1. Build the image (one-time, Maven runs inside Docker)

```sh
docker build -t coav-gui-backend:v1 ./coav-gui/backend
```

### 2a. Mock mode — no Azure credentials needed

```sh
docker run -d -p 8080:8080 \
  -e SPRING_PROFILES_ACTIVE=mock \
  --name coav-backend \
  coav-gui-backend:v1

curl http://localhost:8080/api/flights
curl http://localhost:8080/api/issr-zones

docker stop coav-backend && docker rm coav-backend
```

### 2b. Azure mode — live Event Hub data

```sh
export CONN_STR=$(cd terraform && terraform output -raw eventhub_connection_string)

docker run -d -p 8080:8080 \
  -e CONN_STR="$CONN_STR" \
  --name coav-backend \
  coav-gui-backend:v1

curl http://localhost:8080/api/flights

docker stop coav-backend && docker rm coav-backend
```

---

## Run tests

### Option A — Maven installed locally (recommended)

```sh
brew install maven

cd coav-gui/backend
mvn test

# Single test class
mvn test -Dtest=FlightStateStoreTest
```

### Option B — without local Maven (Docker)

```sh
docker run --rm \
  -v "$PWD/coav-gui/backend":/build -w /build \
  maven:3.9-eclipse-temurin-21-alpine \
  mvn test -q
```

Test coverage (104 tests):

| Test class | Tests | What it covers |
|---|---|---|
| `FlightStateStoreTest` | 25 | Fallback zones, `updateIssrZones`, boundary detection, geometry-only `enrichAlert`, WebSocket broadcast |
| `CameraStoreTest` | 27 | Camera-keyed verification store, TTL, whitelist, payload/size validation, `/topic/cameras` broadcast |
| `CorrectionValidationTest` | 11 | Bean Validation boundary tests |
| `AdvisoryServiceTest` | 10 | Advisory lifecycle: generate → FDO accept/reject → cooldown |
| `CorrectionControllerTest` | 8 | POST validation — valid + OWASP A03 cases |
| `FlightSimulatorServiceTest` | 8 | Mock simulator tick behaviour |
| `IssrZoneServiceTest` | 6 | RHi physics (Murphy & Koop 2005) — warm/cold air, empty guard, zone-extent cap |
| `FlightControllerTest` | 5 | REST endpoints (flights, static + dynamic ISSR zones) |
| `CameraControllerTest` | 3 | `/api/cameras` + `/api/camera-verification` |
| `CoavGuiApplicationTest` | 1 | Spring context loads (mock profile) |

---

## Deploy to Kubernetes (Minikube) — superseded

The production deployment is now **Azure Container Apps** (`terraform/app`, single command — see
the [root README](../../README.md#cloud-deployment-azure-container-apps)). The earlier Minikube
deploy of this backend is kept for reference in
[docs/EXPERIMENT_HISTORY.md](../../docs/EXPERIMENT_HISTORY.md#2-superseded--minikube-deploy-of-the-java-backend).

---

## Back to project root
[Main README](../../README.md)
