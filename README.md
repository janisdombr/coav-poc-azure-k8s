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
