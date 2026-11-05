output "id" {
  description = "Gateway resource."
  value       = azurerm_api_management.this.id
}
output "gateway_url" {
  description = "Cloud-aware gateway URL supplied by ARM."
  value       = azurerm_api_management.this.gateway_url
}
