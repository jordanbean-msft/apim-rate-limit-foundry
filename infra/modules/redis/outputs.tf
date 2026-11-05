output "id" {
  description = "Cloud-selected Redis resource."
  value       = var.azure_cloud == "commercial" ? azurerm_managed_redis.commercial[0].id : azurerm_redis_cache.government[0].id
}
output "hostname" {
  description = "Cloud-selected Redis endpoint."
  value       = var.azure_cloud == "commercial" ? azurerm_managed_redis.commercial[0].hostname : azurerm_redis_cache.government[0].hostname
}
output "port" {
  description = "TLS port; Managed Redis does not use Cache's 6380."
  value       = var.azure_cloud == "commercial" ? azurerm_managed_redis.commercial[0].default_database[0].port : azurerm_redis_cache.government[0].ssl_port
}
