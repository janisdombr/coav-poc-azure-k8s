terraform {
  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.0"
    }
  }
}

# Output from ../
data "terraform_remote_state" "azure_infra" {
  backend = "local"

  config = {
    path = "${path.module}/../terraform.tfstate"
  }
}

# init Databricks using workspace from main 
provider "databricks" {
  azure_workspace_resource_id = data.terraform_remote_state.azure_infra.outputs.databricks_workspace_id
}

# budget single-node cluster for PySpark streams
resource "databricks_cluster" "stream_compute" {
  cluster_name            = "coav-pyspark-stream-compute"
  spark_version           = "14.3.x-scala2.12"
  node_type_id            = "Standard_D4s_v5" # change after Azure Free tier will expire
  autotermination_minutes = 20                # remove after prod
  num_workers             = 0
  data_security_mode      = "SINGLE_USER"
  spark_conf = {
    "spark.master" : "local[*]"
    "spark.databricks.cluster.profile" : "singleNode"
  }

  custom_tags = {
    "ResourceClass" = "SingleNode"
  }
}

# secrets
resource "databricks_secret_scope" "coav_scope" {
  name = "coav-secrets"
}

# connection string to secrets
resource "databricks_secret" "eh_conn_string" {
  key          = "eventhub-conn-str"
  string_value = data.terraform_remote_state.azure_infra.outputs.eventhub_connection_string
  scope        = databricks_secret_scope.coav_scope.name
}

# load PySpark script to Databricks workspace
resource "databricks_notebook" "pyspark_script" {
  source = "${path.module}/stream_processor.py"
  path   = "/Shared/stream_processor"
  format = "SOURCE"
}

# job for deploy and run
resource "databricks_job" "stream_job" {
  name = "Run Coav Stream Processing"
  task {
    task_key            = "pyspark_stream_task"
    existing_cluster_id = databricks_cluster.stream_compute.id
    notebook_task {
      notebook_path = databricks_notebook.pyspark_script.path
    }
  }
}
