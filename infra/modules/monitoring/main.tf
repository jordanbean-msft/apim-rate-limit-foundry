resource "azurecaf_name" "log_analytics" {
  name          = var.resource_token
  resource_type = "azurerm_log_analytics_workspace"
  random_length = 0
  clean_input   = true
}
resource "azurecaf_name" "app_insights" {
  name          = var.resource_token
  resource_type = "azurerm_application_insights"
  random_length = 0
  clean_input   = true
}
resource "azurerm_log_analytics_workspace" "law" {
  name                = azurecaf_name.log_analytics.result
  location            = var.location
  resource_group_name = var.resource_group_name
  sku                 = var.config.sku
  retention_in_days   = var.config.retention_in_days
  tags                = var.tags
}
resource "azurerm_application_insights" "appinsights" {
  name                = azurecaf_name.app_insights.result
  location            = var.location
  resource_group_name = var.resource_group_name
  application_type    = "web"
  workspace_id        = azurerm_log_analytics_workspace.law.id
  tags                = var.tags
}
resource "azurecaf_name" "dashboard" {
  name          = var.resource_token
  resource_type = "azurerm_portal_dashboard"
  suffixes      = ["rate-limiter"]
  random_length = 0
  clean_input   = true
}
locals {
  portal_host = var.azure_cloud == "government" ? "portal.azure.us" : "portal.azure.com"
  dashboard_tiles = [
    { query = "monthly-spend", title = "Month-to-date actual USD by model" },
    { query = "budgets", title = "Monthly user / team / department utilization (last observed)" },
    { query = "denials", title = "Budget denials by hierarchy and model" },
    { query = "tokens", title = "Cached / uncached input and output tokens" },
    { query = "chargeback", title = "Business unit / cost center chargeback" },
    { query = "applications", title = "Application subscription attribution" },
    { query = "request-health", title = "Request errors and latency" },
    { query = "event-hub-health", title = "Event Hub ingress / throttling / delivery failures" },
    { query = "usage-unknown", title = "Missing terminal usage — unpriced, never zero" },
  ]
  dashboard_parts = merge(
    {
      "0" = {
        position = { x = 0, y = 0, colSpan = 18, rowSpan = 3 }
        metadata = {
          inputs = []
          type   = "Extension/HubsExtension/PartType/MarkdownPart"
          settings = { content = { settings = {
            title          = "Granular AI rate limiter"
            subtitle       = "Actual usage and monthly soft budgets"
            markdownSource = 1
            content        = <<-MARKDOWN
              **Monthly USD budgets are soft caps.** Every configured user, team and department limit is checked before dispatch; concurrent in-flight calls can overshoot. Only finalized provider usage is charged. Cached input is a subset of input, not additional tokens. Unknown usage is unpriced, never reported as zero.

              Month-to-date spend uses UTC month start; the other activity tables follow the dashboard time picker. Budget utilization is the latest observed monthly counter, not a live Redis read. User references are opaque; subscription IDs attribute applications, not people.

              This dashboard and the portal share the exact persisted KQL below. Traces can be sampled or delayed; the durable usage ledger and authorized chargeback export remain authoritative. Event Hub delivery is best effort, unsampled by APIM, and never retried. Missing ingress is not proof of missing durable accounting. Namespace diagnostics and APIM logger failures show operational delivery health.
            MARKDOWN
          } } }
        }
      }
    },
    {
      for index, tile in local.dashboard_tiles : tostring(index + 1) => {
        position = { x = (index % 2) * 9, y = 3 + floor(index / 2) * 6, colSpan = 9, rowSpan = 6 }
        metadata = {
          type = "Extension/Microsoft_OperationsManagementSuite_Workspace/PartType/LogsDashboardPart"
          inputs = [
            { name = "Scope", value = { resourceIds = [azurerm_log_analytics_workspace.law.id] }, isOptional = true },
            { name = "PartId", value = uuidv5("url", "${var.resource_token}/rate-limiter/${tile.query}"), isOptional = true },
            { name = "Version", value = "2.0", isOptional = true },
            { name = "TimeRange", isOptional = true },
            { name = "Query", value = file("${path.module}/queries/${tile.query}.kql"), isOptional = true },
            { name = "ControlType", value = "AnalyticsGrid", isOptional = true },
            { name = "PartTitle", value = tile.title, isOptional = true },
            { name = "IsQueryContainTimeRange", value = contains(["monthly-spend", "budgets"], tile.query), isOptional = true },
          ]
          settings = { content = {
            PartTitle               = tile.title
            IsQueryContainTimeRange = contains(["monthly-spend", "budgets"], tile.query)
          } }
        }
      }
    }
  )
}
# Dashboards store layout/KQL only and support neither native diagnostics nor app telemetry.
resource "azurerm_portal_dashboard" "rate_limiter" {
  name                = azurecaf_name.dashboard.result
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = merge(var.tags, { "hidden-title" = "Granular AI rate limiter" })
  dashboard_properties = jsonencode({
    lenses = { "0" = { order = 0, parts = local.dashboard_parts } }
    metadata = { model = {
      timeRange    = { value = { relative = { duration = 24, timeUnit = 1 } }, type = "MsPortalFx.Composition.Configuration.ValueTypes.TimeRange" }
      filterLocale = { value = "en-us" }
      filters = { value = { MsPortalFx_TimeRange = {
        model        = { format = "utc", granularity = "auto", relative = "24h" }
        displayCache = { name = "UTC Time", value = "Past 24 hours" }
      } } }
    } }
  })
}
resource "azurerm_role_assignment" "dashboard_reader" {
  name                 = uuidv5("dns", "${azurerm_portal_dashboard.rate_limiter.id}/${var.dashboard_reader_principal_id}/Reader")
  scope                = azurerm_portal_dashboard.rate_limiter.id
  role_definition_name = "Reader"
  principal_id         = var.dashboard_reader_principal_id
}
resource "azurerm_role_assignment" "workspace_reader" {
  name                 = uuidv5("dns", "${azurerm_log_analytics_workspace.law.id}/${var.dashboard_reader_principal_id}/Log Analytics Reader")
  scope                = azurerm_log_analytics_workspace.law.id
  role_definition_name = "Log Analytics Reader"
  principal_id         = var.dashboard_reader_principal_id
}
