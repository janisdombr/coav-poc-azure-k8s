variable "resource_group_name" {
  type    = string
  default = "rg-coav-poc-prod"
}

variable "location" {
  type    = string
  default = "westeurope"
}

variable "eventhub_namespace" {
  type    = string
  default = "evh-ns-coav-poc"
}

variable "eventhub_name" {
  type    = string
  default = "telemetry-adsb-inbound"
}

variable "acr_name" {
  type        = string
  default     = "acrcoavpoc"
  description = "Azure Container Registry name (globally unique, lowercase, no hyphens, 5-50 chars)"
}

variable "deploy_emulator" {
  type        = bool
  default     = true
  description = "Creates the ACI emulator container. Set to false only if you want to skip the emulator."
}
