# COAV — Contrail Avoidance System (PoC)

EUROCONTROL MUAC · Contract ECTL_SRC_260028

[**Live demo: https://coav.dombrovski.lv**](https://coav.dombrovski.lv)

API url: `https://coav-backend.victoriouscliff-165b8274.westeurope.azurecontainerapps.io/api/flights`
_(URL printed by `terraform output demo_url` after cloud deployment)_

<img src="images/frontend.png" width="1439" />

**Stack:** Raspberry Pi / ACI edge · Azure Event Hubs · Java 21 Spring Boot · Vue 3 + TypeScript ·
U-Net contrail segmentation · Terraform · GitHub Actions CI/CD

**Contents:** [Architecture](#architecture) · [Edge AI model](#edge-ai--contrail-detection-model) ·
[Local dev & testing](#local-development--testing) ·
[Cloud deployment](#cloud-deployment-azure-container-apps) · [CI/CD](#cicd-github-actions) ·
[API reference](#api-reference) · [Event Hub](#event-hub-architecture) ·
[Project structure](#project-structure) ·
[Experiment history](EXPERIMENT_HISTORY.md)

---

## Architecture

```
[Raspberry Pi / ACI]               [Azure]                         [3-tier ATC Workflow]
  edge-emulator/emulator.py  →  Event Hub (telemetry-adsb-inbound)  →  Vue 3 GUI
  edge-pi/node/capture.js    ↗  Spring Boot backend                     Supervisor  — GO/NOGO
                                 FlightStateStore (5-min TTL)            FDO         — advisory queue
                                 trajectory projection (+20 min)         ATCO        — corrections
                                 AdvisoryService (auto-generate)         Leaflet map / Chart.js
                                 WebSocket broadcast every 2s
```

**ISSR zones — single source of truth in `FlightStateStore.ISSR_ZONES`:**
- Zone Alpha: lat 50.20–51.00, lon 3.80–5.40, FL330–FL380 (Brussels convergence)
- Zone Bravo: lat 51.30–52.50, lon 5.80–8.20, FL310–FL370 (Dutch-German border)

**Alert states — pure ISSR geometry (enriched in `FlightStateStore.enrichAlert()`):**

| State | Condition |
|---|---|
| `CRITICAL` | Flight is currently inside an ISSR zone |
| `APPROACHING` | Trajectory projection (20×1-min steps) shows entry within 20 min |
| `null` | Normal |

> Alerts depend **only** on flight geometry vs ISSR zones — never on the camera
> `contrail_detected` flag. Ground-camera detection is a **decoupled verification channel**
> (see *Camera verification* below), not an alert trigger.

Full architecture: PoC vs Production comparison, data flow diagram, alert state machine →
[ARCHITECTURE.md](ARCHITECTURE.md)

---

## Edge AI — Contrail Detection Model

The edge device runs a **U-Net + EfficientNet-B2** segmentation model trained on
[GVCCS](https://zenodo.org/records/15743988) — the only public ground-camera contrail
dataset, recorded at EUROCONTROL MUAC Brétigny-sur-Orge (CC BY 4.0).

| Metric | Value |
|---|---|
| Architecture | U-Net + EfficientNet-B2 (7M params) |
| Dataset | GVCCS · 24,228 frames · 111,761 polygon annotations |
| Best val Dice | **0.8394** (global, calibrated, WR-2 epoch 88 of 90, t=0.50) |
| Latest run | WR-3 + SWA · 120 epochs · plateau confirmed (per-batch EMA 0.8343, SWA avg 0.8249 — worse, kept EMA) |
| PoC threshold | 0.75 ✓ |
| Loss | Dice + Focal Loss (γ=2, α=0.25) |
| Training | Kaggle T4 · 3× Warm Restart · SWA · HuggingFace Hub |

<img src="images/training_curves_final.png" width="1042" />

<img src="images/inference_samples.png" width="1030" />

Full training history, model selection rationale, and deployment instructions →
[edge-pi/README.md](edge-pi/README.md)

---

# LOCAL DEVELOPMENT & TESTING

## Quick start — no Azure needed (mock mode)

The fastest way to see the GUI running. The backend's `mock` profile runs a built-in flight
simulator, so no Event Hub or credentials are required. ISSR zones are still live (Open-Meteo).

> Use **Docker Desktop**, not the minikube Docker context. If you previously ran
> `eval $(minikube docker-env)`, reset it first: `eval $(minikube docker-env -u)`

**1. Backend** — build once, then run in mock mode:

```sh
docker build -t coav-gui-backend:v1 ./coav-gui/backend
docker run -d -p 8080:8080 -e SPRING_PROFILES_ACTIVE=mock --name coav-backend coav-gui-backend:v1
curl http://localhost:8080/api/flights
curl http://localhost:8080/api/issr-zones
```

**2. Frontend** — Vite dev server on `http://localhost:5173`, proxying `/api` and `/ws` to `:8080`. `npm install` is only needed the first time.

```sh
cd coav-gui/frontend
npm install
npm run dev
```

Stop the backend when done:

```sh
docker stop coav-backend && docker rm coav-backend
```

<img src="images/javaspringtests.png" width="581" />

## Full local pipeline — with Azure Event Hub

Runs the real edge→cloud data path: the emulator publishes ADS-B + camera telemetry to Event
Hub, and the backend consumes it live.

Prerequisites — terraform, python3, azure-cli:

```sh
brew install terraform python azure-cli
cd edge-emulator && pip3 install -r requirements.txt && cd ..
az login
```

**1. Provision test infrastructure** (Event Hub, Storage, Databricks workspace):

```sh
cd terraform
terraform init
terraform apply
export CONN_STR=$(terraform output -raw eventhub_connection_string)
```
<img src="images/tf-apply.png" width="544" />

**2. Start the emulator** — 7 aircraft: 4 transit corridors (BAW/DLH/KLM/AFR), 2 holding stacks (BEL256 Brussels DENUT / KLM892 Amsterdam SUGOL), 1 departure (TUI6KL). Each transit flight keeps its callsign for the full crossing — no synchronized resets.

```sh
cd ../edge-emulator
python3 emulator.py
```
<img src="images/emulating.png" width="644" />

**3. Backend in Azure mode** — consumes live Event Hub data (skip the `build` if you already built the image above):

```sh
docker build -t coav-gui-backend:v1 ./coav-gui/backend
docker run -d -p 8080:8080 -e CONN_STR="$CONN_STR" --name coav-backend coav-gui-backend:v1
curl http://localhost:8080/api/flights
docker stop coav-backend && docker rm coav-backend
```

Destroy the stack when done to save money:

```sh
cd ../terraform && terraform destroy -auto-approve
```
<img src="images/tf-destroy.png" width="457" />

## Tests

All of these run automatically in CI (`.github/workflows/ci.yml`, path-filtered).

Backend — 104 JUnit tests (Maven runs inside Docker; no local JDK needed):

```sh
docker run --rm -v "$PWD/coav-gui/backend":/build -w /build \
  maven:3.9-eclipse-temurin-21-alpine mvn test
```

Emulator — 24 tests (incl. OWASP input validation):

```sh
cd edge-emulator && python3 -m pytest test_emulator.py -v && cd ..
```

Edge-Pi inference — 71 tests:

```sh
cd edge-pi/python && python3 -m pytest test_inference.py test_capture.py -v && cd ../..
```

Frontend — unit + Playwright E2E:

```sh
cd coav-gui/frontend && npm test && npm run test:e2e && cd ../..
```
<img src="images/pytest.png" width="755" />

Full backend command reference → [coav-gui/backend/README.md](coav-gui/backend/README.md)

## Superseded & optional paths

Earlier prototype paths (Python K8s backend, Minikube deploys) and optional sub-systems (the
Databricks stream-processing job), plus the real engineering problems solved along the way, are
documented in → **[EXPERIMENT_HISTORY.md](EXPERIMENT_HISTORY.md)**. None of them are
needed to reproduce the current demo.

---

# CLOUD DEPLOYMENT (Azure Container Apps)

Full always-on deployment with public HTTPS URL for the demo.
All three services run in Azure: emulator (ACI) + backend (Container App) + frontend (Container App).

> **ACR is private.** Only authenticated Azure identities can push/pull images.
> `admin_enabled = true` creates a technical user for Container Apps/ACI — it does NOT make
> images publicly accessible.

## Deploy — single command

Requires `terraform/main.tf` already applied (Event Hub must exist).
Docker Desktop must be running and `az login` completed.

```sh
cd terraform/app
terraform init
terraform apply
```

`terraform apply` does everything in order automatically:
1. Registers Azure providers (`Microsoft.App`, `Microsoft.ContainerRegistry`, etc.)
2. Creates ACR, Log Analytics, Container Apps environment
3. Creates Container Apps with a public placeholder image (avoids chicken-and-egg problem)
4. Builds all 3 Docker images locally and pushes them to ACR
5. Updates Container Apps with real images via `az containerapp update`
6. Creates ACI emulator (image is now in ACR)

## Get the demo URL

```sh
terraform output demo_url
```

Share this HTTPS URL. The frontend proxies `/api` and `/ws` to the backend automatically.

## Update after code changes

Force a full rebuild (all 3 images) and roll the Container Apps:

```sh
terraform apply -replace=null_resource.build_images
```

`null_resource.build_images` rebuilds + pushes all three images; `null_resource.update_apps`
then runs automatically (it triggers on the new build ID) and updates both Container Apps with
a fresh `DEPLOY_TIME` env var so they pull the new `:latest`. The ACI emulator is restarted
separately (see below) or via CD.

> **Note:** for routine code changes you normally don't run this by hand — the GitHub Actions
> **CD pipeline** builds and deploys only the changed component on every push to `main`
> (see *CI/CD* below).

Or rebuild a single image manually:

```sh
az acr login --name acrcoavpoc
docker build -t acrcoavpoc.azurecr.io/coav-backend:latest ./coav-gui/backend
docker push acrcoavpoc.azurecr.io/coav-backend:latest
az containerapp update --name coav-backend --resource-group rg-coav-poc-prod \
  --image acrcoavpoc.azurecr.io/coav-backend:latest
```

## Custom domain (Cloudflare)

To serve the frontend at your own domain (e.g. `coav.dombrovski.lv`):

**Step 1 — Cloudflare: add two DNS records**

| Type | Name | Target | Proxy |
|---|---|---|---|
| `CNAME` | `coav` | `coav-frontend.<hash>.westeurope.azurecontainerapps.io` | **DNS only** (grey cloud) |
| `TXT` | `asuid.coav` | value printed by `hostname add` below | DNS only |

Get the CNAME target: `terraform output demo_url` (strip `https://`).

> Keep Proxy **off** — Cloudflare Proxy drops WebSocket connections after 100 s.
> If you need it on: Cloudflare → Network → WebSockets → On.

**Step 2 — Azure: get the TXT verification value**

```sh
az containerapp hostname add \
  --name coav-frontend \
  --resource-group rg-coav-poc-prod \
  --hostname coav.dombrovski.lv
```

This command fails on purpose — it prints the required TXT record value in the error message:
`A TXT record pointing from asuid.coav.dombrovski.lv to <HASH> was not found.`

Add that `<HASH>` as the TXT record in Cloudflare (step 1 above), then wait ~1 min.

**Step 3 — re-run `hostname add` (now succeeds)**

```sh
az containerapp hostname add \
  --name coav-frontend \
  --resource-group rg-coav-poc-prod \
  --hostname coav.dombrovski.lv
```

**Step 4 — bind and issue Let's Encrypt certificate**

```sh
az containerapp hostname bind \
  --name coav-frontend \
  --resource-group rg-coav-poc-prod \
  --hostname coav.dombrovski.lv \
  --environment cae-coav \
  --validation-method CNAME
```

Azure issues the certificate automatically (up to 20 min). No frontend code changes needed —
`BACKEND_URL` is injected at container startup via `/config.js`.

## Teardown cloud deployment

GUI + emulator + ACR:

```sh
cd terraform/app && terraform destroy -auto-approve
```

Event Hub + Storage + Databricks:

```sh
cd terraform && terraform destroy -auto-approve
```

---

# CI/CD (GitHub Actions)

Two workflows in `.github/workflows/` run on every push / PR to `main`. Both are
**path-filtered** — only the components you actually changed are built and tested, so a
docs-only or single-service change stays fast. Doc/image-only pushes (`**.md`, `images/**`)
skip both pipelines entirely.

## CI — `ci.yml` (test gate)

Runs on push **and** pull requests to `main`. A `changes` job (`dorny/paths-filter`) decides
which downstream jobs run:

| Job | Runs when | What it does |
|---|---|---|
| `backend-tests` | `coav-gui/backend/**` | 104 JUnit tests via the Maven Docker image (no local JDK needed) |
| `frontend-build` | `coav-gui/frontend/**` | `npm ci` → type-check + `npm run build` → unit tests; also greps for forbidden relative `fetch('/api…')` calls (prod uses `window.BACKEND_URL`) |
| `edge-pi-tests` | `edge-pi/**` | pytest `test_inference.py` + `test_capture.py` (opencv + pydantic only, **no torch**) |
| `emulator-tests` | `edge-emulator/**` | pytest `test_emulator.py` |
| `playwright-e2e` | frontend or backend changed | Boots backend in `mock` mode (Docker), runs Playwright Chromium E2E; uploads the report artifact on failure |
| `k6-smoke` | `k6/**` or backend changed | Boots mock backend, runs `k6/smoke.js` API smoke tests |

`ci.yml` also exposes `workflow_call`, so the CD pipeline can invoke it as a gate (in that
mode all filters are forced `true` — the full suite runs before any deploy).

## CD — `cd.yml` (deploy to Azure)

Runs on push to `main` only. Steps:

1. **`ci`** — calls `ci.yml` via `workflow_call` (full suite) as a green gate.
2. **`changes`** — re-computes the *real* diff (backend / frontend / emulator).
3. **`deploy`** — gated on the `production` GitHub Environment (add a required reviewer there
   for manual approval). For each changed component only: `docker build` → push to ACR
   (`acrcoavpoc`) → `az containerapp update` with a fresh `DEPLOY_TIME` (backend/frontend, with
   3× retry) or `az container restart` (ACI emulator). A `concurrency` group serialises
   deploys so two never overlap.

### One-time setup for CD

CD authenticates to Azure with a service principal stored as a repo secret.

Create a service principal scoped to the resource group and capture its JSON output:

```sh
az ad sp create-for-rbac \
  --name coav-github-cd \
  --role contributor \
  --scopes /subscriptions/<SUB_ID>/resourceGroups/rg-coav-poc-prod \
  --sdk-auth
```

- Save the full JSON output as the GitHub repo secret **`AZURE_CREDENTIALS`**
  (Settings → Secrets and variables → Actions).
- Create a GitHub **Environment** named `production` (Settings → Environments). Add a
  required reviewer if you want manual approval before each deploy.
- The SP needs `AcrPush` + `Contributor` on the resource group (the command above covers both
  via `contributor`).

> The pipeline pushes to ACR and updates the *existing* Container Apps / ACI created by
> `terraform/app`. It does **not** run Terraform — infrastructure changes are still applied
> manually with `terraform apply`. CD only ships new container images.

---

## API reference

### Flight data

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/flights` | Active flights (5-min TTL, sorted newest first). Each flight includes `alert` (`CRITICAL` / `APPROACHING` / null — pure ISSR geometry), `heading` (degrees), `approachingZoneId`, `approachingMinutes`. |
| GET | `/api/issr-zones` | ISSR zone definitions (ALPHA + BRAVO) with lat/lon/alt bounds and severity. |

### Camera verification (decoupled ground channel)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/cameras` | The 4 all-sky ground cameras (`id`, `lat`, `lon`, `elevationCutoffDeg`). Static config. |
| GET | `/api/camera-verification` | Latest per-camera U-Net detection state (5-min TTL): `confidence`, `contrailPixelRatio`, `contrailCount`, `newContrailCount`, `frameRef`, downscaled `maskPngB64`. |

Camera messages are **camera-keyed** (`EDGE_VISION_AI` carries `camera_id`, **not** `flight_id`).
There is **no camera→flight binding on the backend** — FOV intersection (which camera can see an
alerting flight) is computed on the frontend for map highlighting. Physically the data is one
EHBK GVCCS camera (Brétigny, CC BY 4.0) time-sliced across 4 notional positions — an
illustration of the planned network, honestly labelled in the UI.

### 3-tier ATC workflow

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/advisory` | Pending advisories for FDO review. Auto-generated when a flight is `APPROACHING`. |
| POST | `/api/advisory/accept` | FDO accepts advisory `{ "advisoryId": "<uuid>" }`. Clears from queue, broadcasts. Blocked by Supervisor NO GO on frontend. |
| POST | `/api/advisory/reject` | FDO rejects advisory. Flight enters 5-min cooldown — no new advisory until cooldown expires. |
| POST | `/api/correction` | ATCO issues FL correction `{ "flightId", "newAltitudeFt", "reason" }`. OWASP A03 validated, rate-limited 10 req/min per IP. |

**WebSocket topics (STOMP over SockJS `/ws`):**
- `/topic/flights` — full flight list, pushed every 2 s by `FlightStateStore`
- `/topic/advisories` — pending advisory list, pushed on any change
- `/topic/corrections` — correction acknowledgement after ATCO action
- `/topic/cameras` — per-camera verification state, pushed by `CameraStore` on update

**Advisory flow:** `FlightStateStore.enrichAlert()` runs flat-earth trajectory projection (20 one-minute steps). On `APPROACHING`, `AdvisoryService` auto-generates one advisory per flight with recommended FL±2000ft. FDO accepts or rejects; accepted advisories enable the ATCO correction form. Rejected flights are suppressed for 5 min. Advisory does **not** modify simulator trajectory (PoC scope).

**Correction flow:** `POST /api/correction` validates input (OWASP A03), enforces sliding-window rate limit (OWASP A04), returns `CorrectionResult`, broadcasts via WebSocket. Does **not** write to Event Hub (production would publish to `atc-commands` hub entity).

---

## Event Hub architecture

Single namespace `evh-ns-coav-poc`, one hub entity `telemetry-adsb-inbound`.
Two message types filtered in Java by the `message_type` JSON field:

| `message_type` | Source | Consumed by |
|---|---|---|
| `ADSB_TELEMETRY` | emulator.py / edge-pi | EventHubListenerService → ADSB state map (flight-keyed) |
| `EDGE_VISION_AI` | emulator.py / edge-pi | EventHubListenerService → `CameraStore` (camera-keyed, `camera_id`) |

`ADSB_TELEMETRY` drives flights (keyed by `flight_id`); `EDGE_VISION_AI` drives the decoupled
camera verification channel (keyed by `camera_id`, no `flight_id`).
EventHubListenerService starts from events enqueued within the last **15 minutes** to skip stale
historical data (`EventPosition.fromEnqueuedTime(now - 15 min)`).

---

## Project structure

```
coav-poc-azure-k8s/
├── .github/workflows/
│   ├── ci.yml                       — path-filtered test gate (Maven / Vue / pytest / Playwright / k6)
│   └── cd.yml                       — build + push changed images, roll Azure Container Apps / ACI
├── terraform/
│   ├── main.tf / variables.tf       — Event Hub, Databricks, Storage
│   ├── databricks/                  — Databricks workspace + job
│   └── app/                         — Container Apps + ACR + ACI emulator (cloud deploy)
├── edge-emulator/
│   ├── emulator.py                  — Stateful 7-aircraft MUAC sim → Event Hub
│   └── Dockerfile
├── edge-pi/                         — [README](edge-pi/README.md)
│   ├── node/capture.js              — Node.js: USB webcam → Event Hub
│   ├── python/capture.py            — Python: Pi Camera → Event Hub
│   ├── python/train.py              — Standalone training script (Azure VM / Linux)
│   ├── kaggle_train_contrail_v2.ipynb — Kaggle training notebook with HF checkpoint saves
│   ├── colab_train_contrail_v3.ipynb  — Google Colab version with Drive persistence
│   └── TRAINING_LOG.md              — Full training history (120 epochs, best global val Dice 0.8394)
├── backend/
│   └── main.py                      — Python K8s backend v1 (initial prototype; superseded by
│                                      coav-gui/backend once the Java requirement was found in the spec)
├── coav-gui/
│   ├── backend/                     — Java Spring Boot 3 (104 tests, mock + EventHub modes)
│   └── frontend/                    — Vue 3 + Vite + TypeScript
│       ├── Dockerfile               — nginx multi-stage, BACKEND_URL injected at runtime
│       └── nginx.conf               — serves /config.js with backend URL for direct browser calls
└── k8s/
    └── coav-gui-backend-deployment.yaml
```
