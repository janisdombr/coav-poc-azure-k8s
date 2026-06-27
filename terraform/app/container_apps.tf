# Container Apps managed environment (shared networking + logging)
resource "azurerm_container_app_environment" "coav" {
  name                       = "cae-coav"
  location                   = data.azurerm_resource_group.coav.location
  resource_group_name        = data.azurerm_resource_group.coav.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.coav.id

  depends_on = [azurerm_resource_provider_registration.microsoft_app]
}

# ── Backend: Spring Boot (EventHub mode) ─────────────────────────────────────
resource "azurerm_container_app" "backend" {
  name                         = "coav-backend"
  container_app_environment_id = azurerm_container_app_environment.coav.id
  resource_group_name          = data.azurerm_resource_group.coav.name
  revision_mode                = "Single"

  # Images are built and pushed by null_resource.build_images before Container Apps are created
  depends_on = [null_resource.build_images]

  template {
    min_replicas = 1
    max_replicas = 2

    container {
      name   = "backend"
      image  = "${azurerm_container_registry.coav.login_server}/coav-backend:latest"
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "CONN_STR"
        # EntityPath required — namespace-level string alone causes 'eventHubName cannot be null'
        value = "${data.azurerm_eventhub_namespace_authorization_rule.root.primary_connection_string};EntityPath=${var.eventhub_name}"
      }
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8080
    transport        = "auto"

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  registry {
    server               = azurerm_container_registry.coav.login_server
    username             = azurerm_container_registry.coav.admin_username
    password_secret_name = "acr-password"
  }

  secret {
    name  = "acr-password"
    value = azurerm_container_registry.coav.admin_password
  }
}

# ── Frontend: Vue 3 served via nginx with API proxy ──────────────────────────
resource "azurerm_container_app" "frontend" {
  name                         = "coav-frontend"
  container_app_environment_id = azurerm_container_app_environment.coav.id
  resource_group_name          = data.azurerm_resource_group.coav.name
  revision_mode                = "Single"

  depends_on = [azurerm_container_app.backend, null_resource.build_images]

  template {
    min_replicas = 1
    max_replicas = 2

    container {
      name   = "frontend"
      image  = "${azurerm_container_registry.coav.login_server}/coav-frontend:latest"
      cpu    = 0.25
      memory = "0.5Gi"

      env {
        # HTTPS URL passed to browser via /config.js — browser calls backend directly (CORS).
        # nginx no longer proxies /api or /ws.
        name  = "BACKEND_URL"
        value = "https://${azurerm_container_app.backend.ingress[0].fqdn}"
      }
    }
  }

  ingress {
    external_enabled = true
    target_port      = 80
    transport        = "http"

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  registry {
    server               = azurerm_container_registry.coav.login_server
    username             = azurerm_container_registry.coav.admin_username
    password_secret_name = "acr-password"
  }

  secret {
    name  = "acr-password"
    value = azurerm_container_registry.coav.admin_password
  }
}
