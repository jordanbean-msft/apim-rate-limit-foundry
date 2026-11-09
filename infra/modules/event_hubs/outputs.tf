output "id" {
  description = "Usage event hub ARM resource ID."
  value       = azurerm_eventhub.usage.id
  depends_on  = [time_sleep.propagation, azurerm_private_endpoint.this]
}
output "name" {
  description = "Usage event hub name."
  value       = azurerm_eventhub.usage.name
}
output "namespace_name" {
  description = "Usage namespace name."
  value       = azurerm_eventhub_namespace.this.name
}
output "endpoint_address" {
  description = "Cloud-correct namespace hostname for APIM's MI logger."
  value       = "${azurerm_eventhub_namespace.this.name}.${var.azure_cloud == "government" ? "servicebus.usgovcloudapi.net" : "servicebus.windows.net"}"
}
