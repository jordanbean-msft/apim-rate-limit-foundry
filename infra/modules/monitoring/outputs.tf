output "log_analytics_workspace_name" {
  description = "Log Analytics workspace name."
  value       = azurerm_log_analytics_workspace.law.name
}

output "app_insights_name" {
  description = "Application Insights resource name."
  value       = azurerm_application_insights.appinsights.name
}

output "app_insights_connection_string" {
  description = "Application Insights connection string."
  value       = azurerm_application_insights.appinsights.connection_string
  sensitive   = true
}

output "app_insights_instrumentation_key" {
  description = "Application Insights instrumentation key."
  value       = azurerm_application_insights.appinsights.instrumentation_key
  sensitive   = true
}
output "workspace_id" {
  description = "Shared Log Analytics destination."
  value       = azurerm_log_analytics_workspace.law.id
}
output "app_insights_id" {
  description = "Application Insights resource."
  value       = azurerm_application_insights.appinsights.id
}
