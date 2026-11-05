output "AZURE_RESOURCE_GROUP" {
  description = "Pre-created resource group used by azd."
  value       = data.azurerm_resource_group.rg.name
}
output "AZURE_FUNCTION_NAME" {
  description = "Function app deployment target."
  value       = local.names.function
}
output "AZURE_WEB_NAME" {
  description = "Portal App Service deployment target."
  value       = local.names.web
}
output "API_BASE_URL" {
  description = "Portal API collection root."
  value       = "${module.apim.gateway_url}/portal"
}
output "GATEWAY_URL" {
  description = "AI gateway URL; private deployment requires private routing."
  value       = module.apim.gateway_url
}
output "WEB_URL" {
  description = "Portal URL."
  value       = local.web_url
}
output "WEB_CLIENT_ID" {
  description = "Public SPA application client ID."
  value       = module.identity.web_client_id
}
output "API_AUDIENCE" {
  description = "Limiter API application audience."
  value       = module.identity.api_audience
}
output "API_SCOPE" {
  description = "Delegated portal scope."
  value       = "${module.identity.api_audience}/access_as_user"
}
output "APPLICATIONINSIGHTS_CONNECTION_STRING" {
  description = "Workspace-backed application telemetry."
  value       = module.monitoring.app_insights_connection_string
  sensitive   = true
}
output "TABLE_ENDPOINT" {
  description = "Durable repository endpoint."
  value       = module.storage.table_endpoint
  sensitive   = true
}
output "REDIS_HOST" {
  description = "Private Redis endpoint."
  value       = module.redis.hostname
  sensitive   = true
}
