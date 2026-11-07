resource "azurecaf_name" "this" {
  name          = var.resource_token
  resource_type = "azurerm_key_vault"
  suffixes      = ["portal"]
  random_length = 0
  clean_input   = true
}
resource "azurerm_key_vault" "this" {
  name                          = azurecaf_name.this.result
  location                      = var.location
  resource_group_name           = var.resource_group_name
  tenant_id                     = var.tenant_id
  sku_name                      = var.config.sku_name
  soft_delete_retention_days    = var.config.soft_delete_retention_days
  purge_protection_enabled      = var.config.purge_protection_enabled
  rbac_authorization_enabled    = true
  public_network_access_enabled = var.public_network_access_enabled
  tags                          = var.tags
}
resource "azurerm_role_assignment" "deployer" {
  name                 = uuidv5("dns", "${azurerm_key_vault.this.id}/${var.deployer_principal_id}/Key Vault Secrets Officer")
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = var.deployer_principal_id
}
resource "azurerm_role_assignment" "web" {
  name                 = uuidv5("dns", "${azurerm_key_vault.this.id}/${var.web_principal_id}/Key Vault Secrets User")
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = var.web_principal_id
}
resource "time_sleep" "propagation" {
  create_duration = var.config.propagation_wait_duration
  depends_on      = [azurerm_role_assignment.deployer, azurerm_role_assignment.web]
}
resource "azurerm_key_vault_secret" "portal" {
  name         = "portal-apim-subscription-key"
  value        = var.portal_subscription_key
  key_vault_id = azurerm_key_vault.this.id
  depends_on   = [time_sleep.propagation, azurerm_private_endpoint.this]
}
resource "azurerm_private_endpoint" "this" {
  count               = var.public_network_access_enabled ? 0 : 1
  name                = "${azurerm_key_vault.this.name}-pe"
  location            = var.location
  resource_group_name = var.resource_group_name
  subnet_id           = var.private_endpoint_subnet_id
  tags                = var.tags
  private_service_connection {
    name                           = "${azurerm_key_vault.this.name}-psc"
    private_connection_resource_id = azurerm_key_vault.this.id
    subresource_names              = ["vault"]
    is_manual_connection           = false
  }
  lifecycle {
    ignore_changes = [private_dns_zone_group]
  }
}
data "azurerm_monitor_diagnostic_categories" "this" {
  resource_id = azurerm_key_vault.this.id
}
resource "azurerm_monitor_diagnostic_setting" "this" {
  name                           = "portal-key-vault"
  target_resource_id             = azurerm_key_vault.this.id
  log_analytics_workspace_id     = var.workspace_id
  log_analytics_destination_type = "Dedicated"
  dynamic "enabled_log" {
    for_each = toset(data.azurerm_monitor_diagnostic_categories.this.log_category_types)
    content {
      category = enabled_log.value
    }
  }
  dynamic "enabled_metric" {
    for_each = toset(data.azurerm_monitor_diagnostic_categories.this.metrics)
    content {
      category = enabled_metric.value
    }
  }
}
