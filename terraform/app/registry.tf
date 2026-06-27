# Azure Container Registry — stores Docker images for all services
resource "azurerm_container_registry" "coav" {
  name                = var.acr_name
  resource_group_name = data.azurerm_resource_group.coav.name
  location            = data.azurerm_resource_group.coav.location
  sku                 = "Basic"
  admin_enabled       = true  # required for Container Apps / ACI image pull

  depends_on = [azurerm_resource_provider_registration.microsoft_container_registry]
}
