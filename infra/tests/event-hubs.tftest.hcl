mock_provider "azurerm" {
  mock_resource "azurerm_eventhub_namespace" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.EventHub/namespaces/sample-events"
    }
  }
  mock_resource "azurerm_eventhub" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.EventHub/namespaces/sample-events/eventhubs/usage"
    }
  }
  mock_data "azurerm_monitor_diagnostic_categories" {
    defaults = { log_category_types = ["OperationalLogs"], metrics = ["AllMetrics"] }
  }
}
mock_provider "azurecaf" {
  mock_resource "azurecaf_name" {
    defaults = { result = "sample-events" }
  }
}
mock_provider "time" {}
variables {
  resource_token                = "sample"
  resource_group_name           = "sample-rg"
  location                      = "eastus2"
  tags                          = {}
  azure_cloud                   = "commercial"
  public_network_access_enabled = false
  private_endpoint_subnet_id    = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.Network/virtualNetworks/existing/subnets/endpoints"
  workspace_id                  = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.OperationalInsights/workspaces/sample"
  gateway_principal_id          = "00000000-0000-0000-0000-000000000007"
  config = {
    sku                 = "Standard", capacity = 1, partition_count = 2, message_retention = 7,
    minimum_tls_version = "1.2", propagation_wait_duration = "60s"
  }
}
run "private_secretless_hub_is_audited_and_sender_is_hub_scoped" {
  command = apply
  module { source = "./modules/event_hubs" }
  assert {
    condition = (
      azurerm_eventhub_namespace.this.local_authentication_enabled == false &&
      azurerm_eventhub_namespace.this.public_network_access_enabled == false &&
      azurerm_role_assignment.sender.scope == azurerm_eventhub.usage.id &&
      azurerm_role_assignment.sender.role_definition_name == "Azure Event Hubs Data Sender" &&
      azurerm_role_assignment.sender.principal_id == var.gateway_principal_id &&
      length(azurerm_private_endpoint.this) == 1 &&
      toset(azurerm_private_endpoint.this[0].private_service_connection[0].subresource_names) == toset(["namespace"]) &&
      azurerm_monitor_diagnostic_setting.this.target_resource_id == azurerm_eventhub_namespace.this.id &&
      azurerm_monitor_diagnostic_setting.this.log_analytics_workspace_id == var.workspace_id &&
      length(azurerm_monitor_diagnostic_setting.this.enabled_log) == 1 &&
      length(azurerm_monitor_diagnostic_setting.this.enabled_metric) == 1
    )
    error_message = "Only APIM may send, scoped to the hub; private-only namespace must export all diagnostics."
  }
}
run "public_opt_in_does_not_create_private_endpoint" {
  command = plan
  module { source = "./modules/event_hubs" }
  variables { public_network_access_enabled = true }
  assert {
    condition     = length(azurerm_private_endpoint.this) == 0 && azurerm_eventhub_namespace.this.public_network_access_enabled
    error_message = "Public opt-in must be explicit and omit private endpoint resources."
  }
}
run "invalid_retention_is_rejected" {
  command = plan
  module { source = "./modules/event_hubs" }
  variables { config = merge(var.config, { message_retention = 30 }) }
  expect_failures = [var.config]
}
