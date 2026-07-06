# Experiment History & Superseded Paths

EUROCONTROL MUAC · COAV PoC

This file collects **things you do *not* need to reproduce the current demo** but that are part
of the project's story: earlier prototype paths that were later superseded, optional/paused
sub-systems, and the real engineering problems solved along the way.

The live demo (https://coav.dombrovski.lv) runs on **Azure Container Apps + ACI** — see the main
[README](../README.md) for the reproduction path that is actually current. Everything below is
either historical or optional.

---

## 1. Superseded — Python K8s backend prototype (`backend/main.py`)

The **first** backend was a Python service (`backend/main.py`) reading Event Hub with Pydantic
validation (OWASP A03), deployed to a local **Minikube** cluster. It was replaced by the Java
Spring Boot service in `coav-gui/backend/` once the technical spec's explicit requirement for a
**Java backend + JS/TS frontend** (TechSpec 3.1(5)) was found. The Python prototype is kept in
the repo as evidence of the migration, not as a live component.

Minikube deploy of the Python prototype (historical):

```sh
brew install kubectl minikube
minikube start --cpus=2 --memory=4096 --driver=docker
kubectl get nodes

# Build inside the cluster daemon
eval $(minikube docker-env)
minikube image build -t coav-backend:v1 ./backend

# Secret + deploy
kubectl create secret generic coav-secrets --from-literal=eventhub-cn="$CONN_STR"
kubectl apply -f k8s/deployment.yaml
kubectl logs deployment/coav-backend-deployment --tail=50 -f

# Tear down
kubectl delete deployment coav-backend-deployment --ignore-not-found=true
kubectl delete secret coav-secrets --ignore-not-found=true
minikube stop && minikube delete --all --purge
```

## 2. Superseded — Minikube deploy of the Java backend

Before Azure Container Apps, the Java backend was also deployed to Minikube. The production
deployment is now `terraform/app` (Container Apps + ACI, single command). The K8s manifest
(`k8s/coav-gui-backend-deployment.yaml`) still exists for reference.

```sh
eval $(minikube docker-env)
minikube image build -t coav-gui-backend:v1 ./coav-gui/backend

kubectl create secret generic coav-secrets --from-literal=eventhub-cn="$CONN_STR"
kubectl apply -f k8s/coav-gui-backend-deployment.yaml

kubectl get pods -l app=coav-gui-backend
kubectl port-forward svc/coav-gui-backend-svc 8080:8080
curl http://localhost:8080/api/flights

# Tear down
kubectl delete -f k8s/coav-gui-backend-deployment.yaml
```

> Local Docker builds must use Docker Desktop — do **not** leave the minikube Docker context
> active. Reset it with `eval $(minikube docker-env -u)`.

## 3. Optional / paused — Databricks stream-processing pipeline

The Databricks Bronze/Silver/Gold PySpark pipeline (`terraform/databricks/stream_processor.py`)
is fully written and its infrastructure is provisioned by Terraform, but the **job runtime is
kept stopped** — at cluster cost it is impractical to run continuously just for a demo, and it is
not on the live-demo path. Provision and run it only if you specifically want to exercise the
lakehouse stage.

Provision:

```sh
cd terraform/databricks
terraform init
terraform apply
```

Run the job via the Databricks CLI:

```sh
brew tap databricks/tap && brew install databricks
export DATABRICKS_AUTH_TYPE="azure-cli"

WORKSPACE_RESOURCE_ID=$(terraform output -raw -state=../terraform.tfstate databricks_workspace_id)
DATABRICKS_HOST="https://$(az resource show --ids "$WORKSPACE_RESOURCE_ID" --query "properties.workspaceUrl" -o tsv)"
export DATABRICKS_HOST
SUBSCRIPTION_ID=$(echo "$WORKSPACE_RESOURCE_ID" | cut -d'/' -f3)
TENANT_ID=$(az account list --query "[?id=='$SUBSCRIPTION_ID'].tenantId" -o tsv)
DATABRICKS_TOKEN=$(az account get-access-token --tenant "$TENANT_ID" \
  --scope "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d/.default" --query "accessToken" -o tsv)
unset DATABRICKS_AUTH_TYPE
export DATABRICKS_TOKEN

JOB_ID=$(databricks jobs list --output JSON | jq -r '.[] | select(.settings.name == "Run Coav Stream Processing") | .job_id')
databricks jobs run-now "$JOB_ID"

# Back to classic auth
unset DATABRICKS_TOKEN
export DATABRICKS_AUTH_TYPE="azure-cli"
```

---

## 4. Engineering problems solved along the way

Real issues hit during development and how they were resolved — useful both as a debugging record
and for explaining design decisions.

### 4.1 Event Hub: stale AMQP links on container restart
**Symptom:** after a Docker restart the new consumer could not connect
(*"Another link with the same name and with different epoch value is trying to connect"*).
**Cause:** Event Hub Standard allows max 5 receivers per partition per consumer group; ghost AMQP
links linger ~30 s after a restart. **Fix:** exponential-backoff reconnect (5→10→20→40→60 s cap)
with explicit client disposal (`try-with-resources`) on every attempt.

### 4.2 Kaggle GPU: DataParallel + PyTorch 2.x → CUDA misaligned address
**Symptom:** `RuntimeError: CUDA error: misaligned address` with `nn.DataParallel` on 2× T4.
**Cause:** PyTorch 2.x is stricter about memory alignment in certain SMP encoder ops when the
batch is split across GPUs. **Fix:** single-GPU training (~40 % slower but stable). Production
answer: `DistributedDataParallel` with proper process groups.

### 4.3 Dice = 0.0000 on empty masks
**Symptom:** validation Dice collapsed to 0 despite sensible predictions. **Cause:**
`Dice = 2·∩ / (pred + target)` is 0/0 when both are empty — which is the *correct* prediction for
a clear-sky frame (~35 % of GVCCS frames have no contrail). **Fix:** True-Negative Dice — return
`1.0` when both prediction and target are empty. Standard practice in medical image segmentation.

### 4.4 CI rebuilt every image on every commit
**Symptom:** any commit (even docs) triggered a ~15-min rebuild of all three images. **Fix:**
`dorny/paths-filter` so each component's jobs run only when its files changed; docs/image-only
pushes skip CI/CD entirely. See the CI/CD section in the README.

### 4.5 ISSR zones hardcoded in three places
**Before:** zone coordinates were duplicated in Java, the Python emulator, and the Python backend
prototype. **Fix:** `IssrZoneService` fetches Open-Meteo every 30 min, computes RHi (Murphy & Koop
2005), clusters into bounding-box zones, and publishes them via `GET /api/issr-zones`. The
frontend **and** the emulator's flight generator now read zones from the API — the single source
of truth — instead of hardcoding.

### 4.6 Cloud emulator produced 0 flights (stale zones)
**Symptom:** after cloud deploy the emulator sent telemetry but no flights matched any zone.
**Cause:** `BACKEND_URL` was not set on the emulator ACI, so it defaulted to `localhost:8080`,
could not fetch `/api/issr-zones`, and flew stale Alpha/Bravo routes that no longer matched the
live dynamic zones. **Fix:** inject `BACKEND_URL` into the emulator container
(`terraform/app/build.tf`); the emulator upgrades to live zones within ~60 s via its adaptive
refresh. `PYTHONUNBUFFERED=1` was added so the diagnostic logs actually appeared.

### 4.7 Emulator hung after adding the camera vision frame
**Symptom:** emulator ran, then froze. **Causes:** (a) an `UnboundLocalError` when
`contrail_count` was read before assignment on the detection path, and (b) oversized colour PNG
payloads (100–139 KB) exceeding the 120 KB Pydantic cap. **Fix:** reorder the computation and
switch the visualisation frame to JPEG quality-75 (payload ~17 KB).

### 4.8 Disjoint ISSR zones → no APPROACHING flights
**Symptom:** after capping zone size, almost no flights ever became `APPROACHING` (the demo's main
feature). **Cause:** the two zones ended up geographically disjoint (Alpha north, Bravo south);
the flight generator used a single global bounding-box centre that fell in the gap between them,
so generated routes missed both. **Fix:** per-zone route generation (holds round-robin the zones,
transit routes are assigned per zone) — CRITICAL share went from ~9 % to ~32 %.

### 4.9 Readiness-by-data health probe (no-downtime redeploys)
The emulator's `/health` endpoint returns 200 **only if it actually emitted a telemetry batch in
the last 15 s** (`HEALTH_FRESH_S`), not merely "process alive". ACI's liveness probe uses it, so a
silently stalled emulator (e.g. a stuck Event Hub call) is restarted automatically instead of
sitting in "Running" while producing nothing.

---

← Back to [README](../README.md) · architecture overview in [ARCHITECTURE.md](../ARCHITECTURE.md)
