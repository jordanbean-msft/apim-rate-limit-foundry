output "function" {
  description = "Function workload identity."
  value       = azurerm_user_assigned_identity.workload["function"]
}
output "gateway" {
  description = "APIM workload identity."
  value       = azurerm_user_assigned_identity.workload["gateway"]
}
output "web" {
  description = "Portal workload identity."
  value       = azurerm_user_assigned_identity.workload["web"]
}
output "api_client_id" {
  description = "Limiter application client ID."
  value       = azuread_application.api.client_id
}
output "api_audience" {
  description = "Limiter identifier URI."
  value       = azuread_application_identifier_uri.api.identifier_uri
}
output "web_client_id" {
  description = "SPA public client ID."
  value       = azuread_application.web.client_id
}
