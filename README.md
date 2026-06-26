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