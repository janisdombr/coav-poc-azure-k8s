# Setup provider
terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  features {}
}

# Create Resource Group
resource "azurerm_resource_group" "coav_rg" {
  name     = "rg-coav-poc-prod"
  location = "westeurope"
}

# Create Storage Account
resource "azurerm_storage_account" "coav_storage" {
  name                     = "janisdombrstcoav"
  resource_group_name      = azurerm_resource_group.coav_rg.name
  location                 = azurerm_resource_group.coav_rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
}

# Create Azure Event Hubs Namespace
resource "azurerm_eventhub_namespace" "coav_eh_ns" {
  name                = "evh-ns-coav-poc"
  location            = azurerm_resource_group.coav_rg.location
  resource_group_name = azurerm_resource_group.coav_rg.name
  sku                 = "Standard"
  capacity            = 1
}

# Create Event Hub
resource "azurerm_eventhub" "coav_eh" {
  name                = "telemetry-adsb-inbound"
  namespace_name      = azurerm_eventhub_namespace.coav_eh_ns.name
  resource_group_name = azurerm_resource_group.coav_rg.name
  partition_count     = 2
  message_retention   = 1
}

# SAS Policy
resource "azurerm_eventhub_authorization_rule" "send_rule" {
  name                = "auth-edge-emulator"
  namespace_name      = azurerm_eventhub_namespace.coav_eh_ns.name
  eventhub_name       = azurerm_eventhub.coav_eh.name
  resource_group_name = azurerm_resource_group.coav_rg.name
  listen              = false
  send                = true
  manage              = false
}

# Output connection string
output "eventhub_connection_string" {
  value     = azurerm_eventhub_authorization_rule.send_rule.primary_connection_string
  sensitive = true
}
