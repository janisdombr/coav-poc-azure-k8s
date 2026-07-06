# Builds all Docker images and pushes to ACR.
# Container Apps and ACI depend on this to ensure images exist before creation.
# Re-runs only when ACR changes (first deploy) or when explicitly replaced:
#   terraform apply -replace=null_resource.build_images
resource "null_resource" "build_images" {
  triggers = {
    acr_id = azurerm_container_registry.coav.id
  }

  provisioner "local-exec" {
    working_dir = "${path.root}/../.."
    interpreter = ["/bin/sh", "-c"]
    command     = <<-EOT
      set -e
      echo "==> Logging in to ACR..."
      az acr login --name ${azurerm_container_registry.coav.name}

      echo "==> Building emulator..."
      docker build -t ${azurerm_container_registry.coav.login_server}/coav-emulator:latest ./edge-emulator
      docker push ${azurerm_container_registry.coav.login_server}/coav-emulator:latest

      echo "==> Building backend..."
      docker build -t ${azurerm_container_registry.coav.login_server}/coav-backend:latest ./coav-gui/backend
      docker push ${azurerm_container_registry.coav.login_server}/coav-backend:latest

      echo "==> Building frontend..."
      docker build -t ${azurerm_container_registry.coav.login_server}/coav-frontend:latest ./coav-gui/frontend
      docker push ${azurerm_container_registry.coav.login_server}/coav-frontend:latest

      echo "==> All images pushed."
    EOT
  }
}

# Forces running Container Apps to pull freshly pushed images.
# Triggered automatically when build_images re-runs (new ID after -replace).
resource "null_resource" "update_apps" {
  triggers = {
    build_id = null_resource.build_images.id
  }

  provisioner "local-exec" {
    interpreter = ["/bin/sh", "-c"]
    command     = <<-EOT
      set -e
      echo "==> Updating Container Apps with latest images..."
      DEPLOY_TIME=$(date -u +%Y%m%dT%H%M%SZ)

      az containerapp update \
        --name coav-backend \
        --resource-group ${data.azurerm_resource_group.coav.name} \
        --image ${azurerm_container_registry.coav.login_server}/coav-backend:latest \
        --set-env-vars DEPLOY_TIME="$DEPLOY_TIME"

      az containerapp update \
        --name coav-frontend \
        --resource-group ${data.azurerm_resource_group.coav.name} \
        --image ${azurerm_container_registry.coav.login_server}/coav-frontend:latest \
        --set-env-vars DEPLOY_TIME="$DEPLOY_TIME"

      echo "==> Container Apps updated."
    EOT
  }

  depends_on = [
    azurerm_container_app.backend,
    azurerm_container_app.frontend,
  ]
}

# ACI emulator — created after images are built and pushed
resource "azurerm_container_group" "emulator" {
  count = var.deploy_emulator ? 1 : 0

  name                = "aci-coav-emulator"
  location            = data.azurerm_resource_group.coav.location
  resource_group_name = data.azurerm_resource_group.coav.name
  ip_address_type     = "None"
  os_type             = "Linux"
  restart_policy      = "Always"

  container {
    name   = "emulator"
    image  = "${azurerm_container_registry.coav.login_server}/coav-emulator:latest"
    cpu    = "0.5"
    memory = "0.5"

    environment_variables = {
      CONN_STR = "${data.azurerm_eventhub_namespace_authorization_rule.root.primary_connection_string};EntityPath=${var.eventhub_name}"
      # Without this the emulator defaults to http://localhost:8080 → cannot fetch
      # /api/issr-zones on startup and flies stale Alpha/Bravo routes that don't
      # match the live dynamic zones (it upgrades automatically within ~60s once
      # BACKEND_URL is reachable — see emulator.py main()'s adaptive refresh).
      BACKEND_URL = "https://${azurerm_container_app.backend.ingress[0].fqdn}"
    }

    ports {
      port     = 8081
      protocol = "TCP"
    }

    # Readiness-by-data probe (Option A): the emulator's /health endpoint only
    # returns 200 if it actually sent a telemetry batch within the last 15s
    # (see HEALTH_FRESH_S in emulator.py) — not just "process is running". If
    # the emulator hangs (e.g. stuck Event Hub call) it starts returning 503
    # and ACI restarts the container automatically, instead of silently sitting
    # in "Running" state while producing nothing.
    liveness_probe {
      http_get {
        path = "/health"
        port = 8081
      }
      initial_delay_seconds = 40
      period_seconds        = 30
      failure_threshold     = 3
    }
  }

  image_registry_credential {
    server   = azurerm_container_registry.coav.login_server
    username = azurerm_container_registry.coav.admin_username
    password = azurerm_container_registry.coav.admin_password
  }

  depends_on = [null_resource.build_images]
}
