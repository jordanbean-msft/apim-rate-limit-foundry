mock_provider "azurerm" {
  override_during = plan
  mock_resource "azurerm_log_analytics_workspace" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.OperationalInsights/workspaces/sample"
    }
  }
  mock_resource "azurerm_portal_dashboard" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.Portal/dashboards/sample"
    }
  }
}
mock_provider "azurecaf" {
  override_during = plan
  mock_resource "azurecaf_name" {
    defaults = { result = "sample-dashboard" }
  }
}
variables {
  dashboard_reader_principal_id = "00000000-0000-0000-0000-000000000004"
  resource_token                = "sample"
  resource_group_name           = "sample-rg"
  location                      = "eastus2"
  tags                          = { SecurityControl = "Ignore" }
  config                        = { sku = "PerGB2018", retention_in_days = 30 }
}
run "finalized_usage_catalog_is_the_dashboard_source" {
  command = plan
  module { source = "./modules/monitoring" }
  variables { azure_cloud = "commercial" }
  assert {
    condition = (
      length(jsondecode(azurerm_portal_dashboard.rate_limiter.dashboard_properties).lenses["0"].parts) == 10 &&
      alltrue([for index, name in [
        "monthly-spend", "budgets", "denials", "tokens", "chargeback", "applications",
        "request-health", "event-hub-health", "usage-unknown"
        ] :
        one([for input in jsondecode(azurerm_portal_dashboard.rate_limiter.dashboard_properties).lenses["0"].parts[tostring(index + 1)].metadata.inputs :
          input.value if input.name == "Query"
        ]) == file("modules/monitoring/queries/${name}.kql")
      ])
    )
    error_message = "The portal and deployed dashboard must share the exact v2 KQL catalog with no old accounting tiles."
  }
  assert {
    condition = (
      azurerm_role_assignment.dashboard_reader.role_definition_name == "Reader" &&
      azurerm_role_assignment.dashboard_reader.scope == azurerm_portal_dashboard.rate_limiter.id &&
      azurerm_role_assignment.workspace_reader.role_definition_name == "Log Analytics Reader" &&
      strcontains(output.dashboard_url, "portal.azure.com")
    )
    error_message = "Preserve least-privilege shared-layout access and the commercial dashboard link."
  }
}
run "government_dashboard_link" {
  command = plan
  module { source = "./modules/monitoring" }
  variables { azure_cloud = "government" }
  assert {
    condition     = output.dashboard_url == "https://portal.azure.us/#dashboard/arm${output.dashboard_id}"
    error_message = "Government dashboards must use the sovereign portal."
  }
}
