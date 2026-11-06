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
  resource_token      = "sample"
  resource_group_name = "sample-rg"
  location            = "eastus2"
  tags                = { SecurityControl = "Ignore", environment = "test" }
  config              = { sku = "PerGB2018", retention_in_days = 30 }
}

run "commercial_dashboard_query_binding" {
  command = plan
  module {
    source = "./modules/monitoring"
  }
  variables {
    azure_cloud = "commercial"
  }

  assert {
    condition = alltrue([
      for index, name in [
        "admissions", "denials", "gateway-429", "policy-pressure", "cost-liability",
        "cache-service-units", "latency", "dependency-failures"
      ] :
      one([
        for input in jsondecode(azurerm_portal_dashboard.rate_limiter.dashboard_properties).lenses["0"].parts[tostring(index + 1)].metadata.inputs :
        input.value if input.name == "Query"
      ]) == file("modules/monitoring/queries/${name}.kql")
    ])
    error_message = "Each generated log tile must bind the corresponding reusable query, without substitution."
  }

  assert {
    condition = alltrue([
      for key, part in jsondecode(azurerm_portal_dashboard.rate_limiter.dashboard_properties).lenses["0"].parts :
      part.metadata.type == "Extension/Microsoft_OperationsManagementSuite_Workspace/PartType/LogsDashboardPart" &&
      one([for input in part.metadata.inputs : input.value.resourceIds if input.name == "Scope"]) == [azurerm_log_analytics_workspace.law.id]
      if key != "0"
    ])
    error_message = "Every log tile must use LogsDashboardPart with linked workspace resource context."
  }

  assert {
    condition = alltrue([
      for key, part in jsondecode(azurerm_portal_dashboard.rate_limiter.dashboard_properties).lenses["0"].parts :
      alltrue([
        for input in part.metadata.inputs :
        !can(input.value) if input.name == "TimeRange"
        ]) && one([
        for input in part.metadata.inputs : input.value if input.name == "IsQueryContainTimeRange"
        ]) == false && alltrue([
        for input in part.metadata.inputs : length(regexall("(?i)ago\\s*\\(", input.value)) == 0 if input.name == "Query"
      ])
      if key != "0"
    ]) && jsondecode(azurerm_portal_dashboard.rate_limiter.dashboard_properties).metadata.model.filters.value.MsPortalFx_TimeRange.model.relative == "24h"
    error_message = "The last-24h dashboard filter must reach every tile, without pinned per-tile timespans or hardcoded ago()."
  }

  assert {
    condition = (azurerm_portal_dashboard.rate_limiter.tags["SecurityControl"] == "Ignore" &&
      azurerm_portal_dashboard.rate_limiter.tags["environment"] == "test" &&
      azurerm_portal_dashboard.rate_limiter.tags["hidden-title"] == "Granular AI rate limiter" &&
    output.dashboard_url == "https://portal.azure.com/#dashboard/arm${output.dashboard_id}")
    error_message = "The shared dashboard must retain inherited tags and expose its Commercial portal link."
  }

  assert {
    condition = one([
      for input in jsondecode(azurerm_portal_dashboard.rate_limiter.dashboard_properties).lenses["0"].parts["1"].metadata.inputs :
      input.value.xAxis.name if input.name == "Dimensions"
      ]) == "TimeGenerated" && one([
      for input in jsondecode(azurerm_portal_dashboard.rate_limiter.dashboard_properties).lenses["0"].parts["1"].metadata.inputs :
      input.value.yAxis[0].name if input.name == "Dimensions"
    ]) == "Reservations"
    error_message = "The admissions chart must bind the actual datetime and count columns returned by its query."
  }
}

run "government_dashboard_link" {
  command = plan
  module {
    source = "./modules/monitoring"
  }
  variables {
    azure_cloud = "government"
    location    = "usgovvirginia"
  }
  assert {
    condition     = output.dashboard_url == "https://portal.azure.us/#dashboard/arm${output.dashboard_id}"
    error_message = "Government dashboards must open in the sovereign portal, not portal.azure.com."
  }
}
