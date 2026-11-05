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
}

output "app_insights_instrumentation_key" {
  description = "Application Insights instrumentation key."
  value       = azurerm_application_insights.appinsights.instrumentation_key
}
