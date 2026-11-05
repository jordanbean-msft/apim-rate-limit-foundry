data "azurerm_monitor_diagnostic_categories" "this" {
  for_each    = var.targets
  resource_id = each.value
}
resource "azurerm_monitor_diagnostic_setting" "this" {
  for_each                       = var.targets
  name                           = "${each.key}-all"
  target_resource_id             = each.value
  log_analytics_workspace_id     = var.workspace_id
  log_analytics_destination_type = "Dedicated"
  dynamic "enabled_log" {
    for_each = data.azurerm_monitor_diagnostic_categories.this[each.key].log_category_types
    content {
      category = enabled_log.value
    }
  }
  dynamic "enabled_metric" {
    for_each = data.azurerm_monitor_diagnostic_categories.this[each.key].metrics
    content {
      category = enabled_metric.value
    }
  }
}
