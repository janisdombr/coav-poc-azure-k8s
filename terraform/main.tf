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
  name     = var.resource_group_name
  location = var.location
}

# Create Storage Account
resource "azurerm_storage_account" "coav_storage" {
  name                     = var.storage_account_name
  resource_group_name      = azurerm_resource_group.coav_rg.name
  location                 = azurerm_resource_group.coav_rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
}

# Create Azure Event Hubs Namespace
resource "azurerm_eventhub_namespace" "coav_eh_ns" {
  name                = var.eventhub_namespace
  location            = azurerm_resource_group.coav_rg.location
  resource_group_name = azurerm_resource_group.coav_rg.name
  sku                 = "Standard"
  capacity            = 1
}

# Create Event Hub
resource "azurerm_eventhub" "coav_eh" {
  name                = var.eventhub_name
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
  listen              = true
  send                = true
  manage              = false
}

# Create Databricks Workspace
resource "azurerm_databricks_workspace" "coav_dbw" {
  name                = var.databricks_workspace_name
  resource_group_name = azurerm_resource_group.coav_rg.name
  location            = azurerm_resource_group.coav_rg.location
  sku                 = "premium"
}

# --- OUTPUTS ---

output "eventhub_connection_string" {
  value     = azurerm_eventhub_authorization_rule.send_rule.primary_connection_string
  sensitive = true
}

output "databricks_workspace_id" {
  value       = azurerm_databricks_workspace.coav_dbw.id
  description = "Pass this ID to the internal Databricks provider"
}

output "eventhub_primary_key" {
  value     = azurerm_eventhub_authorization_rule.send_rule.primary_key
  sensitive = true
}

output "eventhub_name" {
  value = azurerm_eventhub_authorization_rule.send_rule.eventhub_name
}

output "eventhub_namespace_name" {
  value = azurerm_eventhub_authorization_rule.send_rule.namespace_name
}

