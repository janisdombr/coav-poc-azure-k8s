# COAV — Contrail Avoidance System (PoC)

EUROCONTROL MUAC · Contract ECTL_SRC_260028

[**Live demo: https://coav.dombrovski.lv**](https://coav.dombrovski.lv)

API url: `https://coav-backend.victoriouscliff-165b8274.westeurope.azurecontainerapps.io/api/flights`
_(URL printed by `terraform output demo_url` after cloud deployment)_

<img src="images/frontend.png" width="1439" />

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

**Alert states (enriched in `FlightStateStore.enrichAlert()`):**

| State | Condition |
|---|---|
| `CRITICAL` | Flight is currently inside ISSR zone |
| `APPROACHING` | Trajectory projection shows entry within 20 min |
| `WARNING` | Contrail detected, not yet in/approaching ISSR |
| `null` | Normal |

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
| Best val Dice | **0.8394** (global, epoch 88 of 90, t=0.50) |
| PoC threshold | 0.75 ✓ |
| Loss | Dice + Focal Loss (γ=2, α=0.25) |
| Training | Kaggle T4 · 2× Warm Restart · SWA · HuggingFace Hub |

<img src="images/training_curves_final.png" width="1042" />

<img src="images/inference_samples.png" width="1030" />

Full training history, model selection rationale, and deployment instructions →
[edge-pi/README.md](edge-pi/README.md)

---

# LOCAL DEVELOPMENT & TESTING

## Prepare env (install terraform, python3, azure cli. See installation instruction for your OS) and auth with Azure

```sh
brew install terraform
brew install python
cd edge-emulator
pip3 install -r requirements.txt
cd ..
brew install azure-cli
az login
```

## Create terraform/main.tf for test infrastructure and deploy it

```sh
cd terraform
terraform init
terraform apply
```
<img src="images/tf-apply.png" width="544" />

## After success put connection string to CONN_STR env

```sh
export CONN_STR=$(terraform output -raw eventhub_connection_string)
```

## Start emulating (edge-emulator/emulator.py)

The emulator generates **7 aircraft**: 4 transit corridors (BAW/DLH/KLM/AFR families),
2 holding stacks (BEL256 Brussels DENUT / KLM892 Amsterdam SUGOL), 1 departure (TUI6KL).
Each transit flight keeps its callsign for the full route crossing, then a new callsign
starts the same corridor after a gap — no synchronized 5-minute resets.

```sh
cd ../edge-emulator
python3 emulator.py
```
<img src="images/emulating.png" width="644" />

## Creating OWASP tests and pass it

```sh
pytest -v
```
<img src="images/pytest.png" width="755" />

## Destroy terraform stack to save money (after all next steps)

```sh
cd ../terraform
terraform destroy -auto-approve
```
<img src="images/tf-destroy.png" width="457" />

## Next step - backend -->
[Backend Readme.md](backend/Readme.md)

## After backend test try Databricks

```sh
cd databricks
terraform init
terraform apply
```

## After creating all resources we need to run job using Databricks CLI
## install if needed
```sh
brew tap databricks/tap
brew trust databricks/tap
brew install databricks
export DATABRICKS_AUTH_TYPE="azure-cli"
```
## run (just run it if you have installed jq already)

```sh
WORKSPACE_RESOURCE_ID=$(terraform output -raw -state=../terraform.tfstate databricks_workspace_id)
DATABRICKS_HOST="https://$(az resource show --ids "$WORKSPACE_RESOURCE_ID" --query "properties.workspaceUrl" -o tsv)"
export DATABRICKS_HOST
SUBSCRIPTION_ID=$(echo "$WORKSPACE_RESOURCE_ID" | cut -d'/' -f3)
TENANT_ID=$(az account list --query "[?id=='$SUBSCRIPTION_ID'].tenantId" -o tsv)
DATABRICKS_TOKEN=$(az account get-access-token \
  --tenant "$TENANT_ID" \
  --scope "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d/.default" \
  --query "accessToken" \
  -o tsv)
unset DATABRICKS_AUTH_TYPE
export DATABRICKS_TOKEN
JOB_ID=$(databricks jobs list --output JSON | jq -r '.[] | select(.settings.name == "Run Coav Stream Processing") | .job_id')
databricks jobs run-now "$JOB_ID"
```
## return back to classic auth
```sh
unset DATABRICKS_TOKEN
export DATABRICKS_AUTH_TYPE="azure-cli"
```

---

## GUI Backend — Java Spring Boot

### Two modes: `mock` (no Azure) or default (reads live from Event Hub).

> **Note:** local Docker runs (`mock` and `Azure mode`) use Docker Desktop — do **not** activate
> the minikube Docker context for these. If you previously ran `eval $(minikube docker-env)`,
> reset it first: `eval $(minikube docker-env -u)`

## Build the image (Docker Desktop, one-time)

```sh
docker build -t coav-gui-backend:v1 ./coav-gui/backend
```

## Mock mode — built-in simulator, no credentials needed

```sh
docker run -d -p 8080:8080 -e SPRING_PROFILES_ACTIVE=mock --name coav-backend coav-gui-backend:v1

curl http://localhost:8080/api/flights
curl http://localhost:8080/api/issr-zones
```

## Stop when done
```sh
docker stop coav-backend && docker rm coav-backend
```

## Azure mode — live Event Hub data

```sh
export CONN_STR=$(cd terraform && terraform output -raw eventhub_connection_string)
docker run -d -p 8080:8080 -e CONN_STR="$CONN_STR" --name coav-backend coav-gui-backend:v1

curl http://localhost:8080/api/flights
```
## Stop when done
```sh
docker stop coav-backend && docker rm coav-backend
```

## Deploy to Minikube cluster (Azure mode)

The minikube Docker context is required here so the image is built inside the cluster node.

```sh
eval $(minikube docker-env)
minikube image build -t coav-gui-backend:v1 ./coav-gui/backend

# Create secret (skip if already exists from a previous deploy)
kubectl create secret generic coav-secrets --from-literal=eventhub-cn="$CONN_STR"

kubectl apply -f k8s/coav-gui-backend-deployment.yaml

# Forward cluster port to localhost
kubectl port-forward svc/coav-gui-backend-svc 8080:8080

curl http://localhost:8080/api/flights
```

Full command reference → [coav-gui/backend/README.md](coav-gui/backend/README.md)

## Run backend tests (44 tests, no Maven install needed)

```sh
docker run --rm -v "$PWD/coav-gui/backend":/build -w /build \
  maven:3.9-eclipse-temurin-21-alpine mvn test
```
<img src="images/javaspringtests.png" width="581" />

## Vue 3 Frontend — local dev

Requires the backend running on :8080.

```sh
cd coav-gui/frontend
npm install   # once
npm run dev   # → http://localhost:5173 (proxy /api and /ws → :8080)
```

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

Force a full rebuild (all 3 images):

```sh
terraform apply -replace=null_resource.build_and_push
```

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

```sh
# GUI + emulator + ACR
cd terraform/app && terraform destroy -auto-approve

# Event Hub + Storage + Databricks
cd terraform && terraform destroy -auto-approve
```

---

## API reference

### Flight data

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/flights` | Active flights (5-min TTL, sorted newest first). Each flight includes `alert` (`CRITICAL` / `APPROACHING` / `WARNING` / null), `heading` (degrees), `approachingZoneId`, `approachingMinutes`. |
| GET | `/api/issr-zones` | ISSR zone definitions (ALPHA + BRAVO) with lat/lon/alt bounds and severity. |

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

**Advisory flow:** `FlightStateStore.enrichAlert()` runs flat-earth trajectory projection (20 one-minute steps). On `APPROACHING`, `AdvisoryService` auto-generates one advisory per flight with recommended FL±2000ft. FDO accepts or rejects; accepted advisories enable the ATCO correction form. Rejected flights are suppressed for 5 min. Advisory does **not** modify simulator trajectory (PoC scope).

**Correction flow:** `POST /api/correction` validates input (OWASP A03), enforces sliding-window rate limit (OWASP A04), returns `CorrectionResult`, broadcasts via WebSocket. Does **not** write to Event Hub (production would publish to `atc-commands` hub entity).

---

## Event Hub architecture

Single namespace `evh-ns-coav-poc`, one hub entity `telemetry-adsb-inbound`.
Two message types filtered in Java by the `message_type` JSON field:

| `message_type` | Source | Consumed by |
|---|---|---|
| `ADSB_TELEMETRY` | emulator.py / edge-pi | EventHubListenerService → ADSB state map |
| `EDGE_VISION_AI` | emulator.py / edge-pi | EventHubListenerService → AI state map |

Stream join fires when both types arrive for the same `flight_id`.
EventHubListenerService starts from events enqueued within the last **15 minutes** to skip stale
historical data (`EventPosition.fromEnqueuedTime(now - 15 min)`).

---

## Project structure

```
coav-poc-azure-k8s/
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
│   └── TRAINING_LOG.md              — Full training history (41 epochs, val Dice 0.7932)
├── backend/
│   └── main.py                      — Python K8s backend v1 (initial prototype; superseded by
│                                      coav-gui/backend once the Java requirement was found in the spec)
├── coav-gui/
│   ├── backend/                     — Java Spring Boot 3 (44 tests, mock + EventHub modes)
│   └── frontend/                    — Vue 3 + Vite + TypeScript
│       ├── Dockerfile               — nginx multi-stage, BACKEND_URL injected at runtime
│       └── nginx.conf               — serves /config.js with backend URL for direct browser calls
└── k8s/
    └── coav-gui-backend-deployment.yaml
```
