variable "resource_group_name" {
  type        = string
  description = "Azure Resource Group Name"
  default     = "rg-coav-poc-prod"
}

variable "location" {
  type        = string
  description = "Azure Region"
  default     = "westeurope"
}

variable "storage_account_name" {
  type        = string
  description = "Azure Storage Account"
  default     = "janisdombrstcoav"
}

variable "eventhub_namespace" {
  type        = string
  description = "Event Hubs Namespace name"
  default     = "evh-ns-coav-poc"
}

variable "eventhub_name" {
  type        = string
  description = "Event Hub hub instance name"
  default     = "telemetry-adsb-inbound"
}

variable "databricks_workspace_name" {
  type        = string
  description = "Name of the Databricks Workspace"
  default     = "dbw-coav-poc"
}
