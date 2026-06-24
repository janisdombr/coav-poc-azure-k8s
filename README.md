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
## After success put connection string to CONN_STR env

```sh
export CONN_STR=$(terraform output -raw eventhub_connection_string)
```

## Start emulating (edge-emulator/emulator.py)

```sh
cd ../edge-emulator
python3 emulator.py
```

## Creating OWASP tests and pass it

```sh
pytest -v
```

## Destroy terraform stack to save money

```sh
cd ../terraform
terraform destroy -auto-approve
```                               
