terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.90"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
  }
}

provider "azurerm" {
  features {}
  # Disable automatic provider registration to avoid conflicts.
  # We register explicitly only what this stack actually uses (see below).
  # skip_provider_registration is the azurerm 3.x equivalent of resource_provider_registrations = "none"
  skip_provider_registration = true
}

# ── Explicit provider registrations ───────────────────────────────────────────
# Required on fresh Pay-As-You-Go subscriptions. Registration takes ~1-2 min each.
# With resource_provider_registrations = "none" there are no auto-registration
# conflicts — this block is the single source of truth for what gets registered.
resource "azurerm_resource_provider_registration" "microsoft_app" {
  name = "Microsoft.App"                # Azure Container Apps
}
resource "azurerm_resource_provider_registration" "microsoft_operational_insights" {
  name = "Microsoft.OperationalInsights" # Log Analytics
}
resource "azurerm_resource_provider_registration" "microsoft_container_registry" {
  name = "Microsoft.ContainerRegistry"  # ACR
}
resource "azurerm_resource_provider_registration" "microsoft_container_instance" {
  name = "Microsoft.ContainerInstance"  # ACI (emulator)
}

# Reference existing resource group created by terraform/main.tf
data "azurerm_resource_group" "coav" {
  name = var.resource_group_name
}

# Reference existing Event Hub namespace to get connection string
data "azurerm_eventhub_namespace" "coav" {
  name                = var.eventhub_namespace
  resource_group_name = data.azurerm_resource_group.coav.name
}

data "azurerm_eventhub_namespace_authorization_rule" "root" {
  name                = "RootManageSharedAccessKey"
  namespace_name      = data.azurerm_eventhub_namespace.coav.name
  resource_group_name = data.azurerm_resource_group.coav.name
}

# Log Analytics workspace — required by Container Apps environment
resource "azurerm_log_analytics_workspace" "coav" {
  name                = "log-coav-app"
  location            = data.azurerm_resource_group.coav.location
  resource_group_name = data.azurerm_resource_group.coav.name
  sku                 = "PerGB2018"
  retention_in_days   = 30

  depends_on = [azurerm_resource_provider_registration.microsoft_operational_insights]
}
