output "demo_url" {
  description = "Public HTTPS URL of the COAV GUI (share this for the demo)"
  value       = "https://${azurerm_container_app.frontend.ingress[0].fqdn}"
}

output "backend_url" {
  description = "Public HTTPS URL of the Spring Boot API"
  value       = "https://${azurerm_container_app.backend.ingress[0].fqdn}"
}

