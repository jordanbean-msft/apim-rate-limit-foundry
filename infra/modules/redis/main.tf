resource "azurerm_managed_redis" "commercial" {
  count                     = var.azure_cloud == "commercial" ? 1 : 0
  name                      = var.name
  resource_group_name       = var.resource_group_name
  location                  = var.location
  sku_name                  = var.config.managed_sku
  high_availability_enabled = var.config.high_availability
  public_network_access     = var.public_network_access_enabled ? "Enabled" : "Disabled"
  default_database {
    access_keys_authentication_enabled = false
    client_protocol                    = "Encrypted"
    clustering_policy                  = "NoCluster"
    eviction_policy                    = "NoEviction"
  }
  tags = var.tags
}
resource "azurerm_managed_redis_access_policy_assignment" "function" {
  count            = var.azure_cloud == "commercial" ? 1 : 0
  managed_redis_id = azurerm_managed_redis.commercial[0].id
  object_id        = var.principal_id
}
resource "azurerm_redis_cache" "government" {
  count                              = var.azure_cloud == "government" ? 1 : 0
  name                               = var.name
  resource_group_name                = var.resource_group_name
  location                           = var.location
  capacity                           = var.config.government_capacity
  family                             = "P"
  sku_name                           = "Premium"
  minimum_tls_version                = var.config.minimum_tls_version
  non_ssl_port_enabled               = false
  public_network_access_enabled      = var.public_network_access_enabled
  access_keys_authentication_enabled = false
  redis_configuration {
    active_directory_authentication_enabled = true
    maxmemory_policy                        = "noeviction"
  }
  tags = var.tags
}
resource "azurerm_redis_cache_access_policy_assignment" "function" {
  count              = var.azure_cloud == "government" ? 1 : 0
  name               = "${var.name}-function"
  redis_cache_id     = azurerm_redis_cache.government[0].id
  access_policy_name = "Data Contributor"
  object_id          = var.principal_id
  object_id_alias    = "limiter-function"
}
resource "azapi_resource" "inspector_commercial" {
  count     = var.azure_cloud == "commercial" && var.config.inspection_enabled ? 1 : 0
  type      = "Microsoft.Cache/redisEnterprise/databases/accessPolicyAssignments@2026-05-01-preview"
  name      = "inspector${replace(var.inspection_principal_id, "-", "")}"
  parent_id = "${azurerm_managed_redis.commercial[0].id}/databases/default"
  body = {
    properties = {
      accessPolicyName = "default"
      accessString     = "+@read +ping +info +scan +client|setinfo ~{limiter}:*"
      user             = { objectId = var.inspection_principal_id }
    }
  }
}
resource "azurerm_redis_cache_access_policy_assignment" "inspector_government" {
  count              = var.azure_cloud == "government" && var.config.inspection_enabled ? 1 : 0
  name               = "${var.name}-inspector"
  redis_cache_id     = azurerm_redis_cache.government[0].id
  access_policy_name = "Data Reader"
  object_id          = var.inspection_principal_id
  object_id_alias    = "limiter-inspector"
}
