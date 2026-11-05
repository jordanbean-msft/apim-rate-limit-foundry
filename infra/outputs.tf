output "APP_INSIGHTS_CONNECTION_STRING" {
  description = "Application Insights connection string."
  value       = module.monitoring.app_insights_connection_string
  sensitive   = true
}

output "APP_INSIGHTS_INSTRUMENTATION_KEY" {
  description = "Application Insights instrumentation key."
  value       = module.monitoring.app_insights_instrumentation_key
  sensitive   = true
}
