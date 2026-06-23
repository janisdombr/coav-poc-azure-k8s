# coav-poc-azure-k8s
Create test env for EUROCONTROL position in COAV project

## Create terraform/main.tf for test infrostructure and deploy it

```sh
terraform init
terraform apply
```
## After success put connection string to CONN_STR env

```sh
export CONN_STR=$(terraform output -raw eventhub_connection_string)
```

## 