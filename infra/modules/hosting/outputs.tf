output "function_id" {
  description = "Function app resource."
  value       = azurerm_linux_function_app.this.id
}
output "web_id" {
  description = "Web app resource."
  value       = azurerm_linux_web_app.this.id
}
output "function_plan_id" {
  description = "Function plan resource."
  value       = azurerm_service_plan.function.id
}
output "web_plan_id" {
  description = "Web plan resource."
  value       = azurerm_service_plan.web.id
}
output "stream_id" {
  description = "Dedicated stream Function resource, when enabled."
  value       = var.streaming_enabled ? azurerm_linux_function_app.stream[0].id : null
}
