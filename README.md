# coav-poc-azure-k8s
Create test env for EUROCONTROL position in COAV project

## Prepare env (install terraform, python3, azure cli. See installation inscruction for your OS) and auth with Azure

```sh
brew install terraform
brew install python
cd edge-emulator
pip3 install -r requirements.txt
cd ..
brew install azure-cli
az login
```

## Create terraform/main.tf for test infrostructure and deploy it

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

```sh
cd ../edge-emulator
python3 emulator.py
```
<img src="images/emulating.png" width="1104" />

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
[Backend Readme.me](backend/Readme.md)


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
# return back to classic auth
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
# Stop when done
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