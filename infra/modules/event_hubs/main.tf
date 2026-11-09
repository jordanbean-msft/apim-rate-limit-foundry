resource "azurecaf_name" "namespace" {
  name          = var.resource_token
  resource_type = "azurerm_eventhub_namespace"
  suffixes      = ["usage"]
  random_length = 0
  clean_input   = true
}
resource "azurecaf_name" "hub" {
  name          = var.resource_token
  resource_type = "azurerm_eventhub"
  suffixes      = ["usage"]
  random_length = 0
  clean_input   = true
}
resource "azurerm_eventhub_namespace" "this" {
  name                          = azurecaf_name.namespace.result
  resource_group_name           = var.resource_group_name
  location                      = var.location
  sku                           = var.config.sku
  capacity                      = var.config.capacity
  minimum_tls_version           = var.config.minimum_tls_version
  public_network_access_enabled = var.public_network_access_enabled
  local_authentication_enabled  = false
  tags                          = var.tags
}
resource "azurerm_eventhub" "usage" {
  name              = azurecaf_name.hub.result
  namespace_id      = azurerm_eventhub_namespace.this.id
  partition_count   = var.config.partition_count
  message_retention = var.config.message_retention
}
resource "azurerm_role_assignment" "sender" {
  name                 = uuidv5("dns", "${azurerm_eventhub.usage.id}/${var.gateway_principal_id}/Azure Event Hubs Data Sender")
  scope                = azurerm_eventhub.usage.id
  role_definition_name = "Azure Event Hubs Data Sender"
  principal_id         = var.gateway_principal_id
}
resource "time_sleep" "propagation" {
  create_duration = var.config.propagation_wait_duration
  depends_on      = [azurerm_role_assignment.sender]
}
resource "azurerm_private_endpoint" "this" {
  count               = var.public_network_access_enabled ? 0 : 1
  name                = "${azurerm_eventhub_namespace.this.name}-pe"
  resource_group_name = var.resource_group_name
  location            = var.location
  subnet_id           = var.private_endpoint_subnet_id
  tags                = var.tags
  private_service_connection {
    name                           = "${azurerm_eventhub_namespace.this.name}-psc"
    private_connection_resource_id = azurerm_eventhub_namespace.this.id
    subresource_names              = ["namespace"]
    is_manual_connection           = false
  }
  lifecycle {
    ignore_changes = [private_dns_zone_group]
  }
}
data "azurerm_monitor_diagnostic_categories" "this" {
  resource_id = azurerm_eventhub_namespace.this.id
}
resource "azurerm_monitor_diagnostic_setting" "this" {
  name                           = "${azurerm_eventhub_namespace.this.name}-diagnostics"
  target_resource_id             = azurerm_eventhub_namespace.this.id
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
