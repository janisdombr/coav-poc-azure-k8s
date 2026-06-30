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
- **`kubectl` + `minikube`** — only for K8s cluster deploy (not needed for local testing)

## API endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/flights` | Active flights updated in the last 5 min (JSON array, newest first) |
| GET | `/api/issr-zones` | ISSR zone definitions (2 hardcoded or N dynamic) |
| POST | `/api/correction` | Submit ATC flight level correction |
| WS | `/ws` (STOMP) | Live flight updates → `/topic/flights` |

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

Test coverage (51 tests):

| Test class | What it covers |
|---|---|
| `CoavGuiApplicationTest` | Spring context loads (mock profile) |
| `FlightStateStoreTest` | Fallback zones, `updateIssrZones`, boundary detection, WebSocket broadcast |
| `FlightSimulatorServiceTest` | Mock simulator tick behaviour |
| `FlightControllerTest` | REST endpoints (flights, static + dynamic ISSR zones) |
| `CorrectionControllerTest` | POST validation — valid + 5 OWASP A03 cases |
| `CorrectionValidationTest` | Bean Validation boundary tests |
| `IssrZoneServiceTest` | RHi physics (Murphy & Koop 2005) — warm/cold air, empty guard |

---

## Deploy to Kubernetes (Minikube)

The minikube Docker context is required here so the image lands inside the cluster node.

```sh
eval $(minikube docker-env)
minikube image build -t coav-gui-backend:v1 ./coav-gui/backend

# Create secret (skip if already exists)
kubectl create secret generic coav-secrets \
  --from-literal=eventhub-cn="$CONN_STR"

kubectl apply -f k8s/coav-gui-backend-deployment.yaml

# Check pod status
kubectl get pods -l app=coav-gui-backend

# Stream logs
kubectl logs deployment/coav-gui-backend-deployment -f

# Forward cluster port to localhost and verify
kubectl port-forward svc/coav-gui-backend-svc 8080:8080
curl http://localhost:8080/api/flights
```

### Tear down

```sh
kubectl delete -f k8s/coav-gui-backend-deployment.yaml
```

---

## Back to project root
[Main README](../../README.md)
