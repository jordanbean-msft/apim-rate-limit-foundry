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
output "AZURE_DASHBOARD_ID" {
  description = "Shared Azure portal rate-limiter dashboard resource ID."
  value       = module.monitoring.dashboard_id
}
output "AZURE_DASHBOARD_URL" {
  description = "Shared rate-limiter dashboard in the selected cloud's Azure portal."
  value       = module.monitoring.dashboard_url
}
output "LOG_ANALYTICS_WORKSPACE_ID" {
  description = "Workspace UUID used by the server-side Azure Monitor Logs SDK."
  value       = module.monitoring.workspace_customer_id
}
output "LOG_ANALYTICS_WORKSPACE_RESOURCE_ID" {
  description = "Fixed workspace resource scope for portal dashboard queries."
  value       = module.monitoring.workspace_id
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
output "LLM_GATEWAY_ROUTES" {
  description = "Enabled public LLM paths and operator-pinned protocol/model aliases."
  value       = module.apim.llm_routes
}
output "FOUNDRY_RESOURCE_ID" {
  description = "Created or referenced Chat account, retained by azd for shared-protocol RBAC deduplication."
  value       = try(module.ai.backends["foundry"].id, "")
}
output "AZURE_STREAM_FUNCTION_NAME" {
  description = "Dedicated HTTP streaming Function service for azd."
  value       = var.streaming.enabled ? local.names.stream : null
}
output "AZURE_STREAM_FUNCTION_ID" {
  description = "Dedicated streaming host resource ID."
  value       = module.hosting.stream_id
}
output "APPLICATION_SUBSCRIPTIONS" {
  description = "Safe inference application metadata only; excludes subscription keys and the server-side portal subscription."
  value       = jsonencode(local.application_registry)
}
output "EVENT_HUB_NAMESPACE_NAME" {
  description = "Native APIM usage telemetry namespace."
  value       = module.event_hubs.namespace_name
}
output "EVENT_HUB_NAME" {
  description = "Native APIM finalized usage export hub."
  value       = module.event_hubs.name
}
output "EVENT_HUB_RESOURCE_ID" {
  description = "Hub-scoped producer authorization and consumer onboarding."
  value       = module.event_hubs.id
}
output "APIM_USAGE_EVENT_URL" {
  description = "Function-only managed-identity callback; not a public client API."
  value       = "${module.apim.gateway_url}/internal/usage-events"
}
