output "id" {
  description = "Storage resource ID."
  value       = azurerm_storage_account.this.id
}
output "name" {
  description = "Host storage account."
  value       = azurerm_storage_account.this.name
}
output "table_endpoint" {
  description = "Entra-authenticated Table endpoint."
  value       = azurerm_storage_account.this.primary_table_endpoint
}
output "blob_endpoint" {
  description = "Exact cloud host blob endpoint."
  value       = azurerm_storage_account.this.primary_blob_endpoint
}
output "queue_endpoint" {
  description = "Exact cloud host queue endpoint."
  value       = azurerm_storage_account.this.primary_queue_endpoint
}
