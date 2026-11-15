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
    { query = "gateway-traffic", title = "APIM inference traffic and HTTP outcomes", chart = "Line", x = "TimeGenerated", y = "Requests", split = "Outcome" },
    { query = "admissions", title = "Function budget admissions and blocks by model", chart = "StackedColumn", x = "Model", y = "Requests", split = "Decision" },
    { query = "tokens", title = "Actual token composition by model", chart = "StackedColumn", x = "Model", y = "Tokens", split = "TokenType" },
    { query = "token-trend", title = "Actual token composition over time (all models)", chart = "StackedColumn", x = "TimeGenerated", y = "Tokens", split = "TokenType" },
    { query = "cache-hit", title = "Input tokens served from provider prompt cache", chart = "Column", x = "Model", y = "CacheHitPercent", split = "" },
    { query = "accounting-pipeline", title = "Function admission-to-accounting lifecycle by model", chart = "Column", x = "Model", y = "Requests", split = "Stage" },
    { query = "function-latency", title = "Function budget-check and usage-recording latency", chart = "Line", x = "TimeGenerated", y = "P95Milliseconds", split = "Stage" },
    { query = "dependency-health", title = "Function Table and Redis operations", chart = "StackedColumn", x = "DependencyOperation", y = "Operations", split = "Outcome" },
    { query = "monthly-spend", title = "Month-to-date actual USD by model", chart = "Column", x = "Model", y = "ActualUSD", split = "" },
    { query = "budgets", title = "Monthly budget utilization (last observed, may exceed 100%)", chart = "Column", x = "BudgetId", y = "UtilizationPercent", split = "" },
    { query = "denials", title = "Blocking-budget matches by hierarchy and model", chart = "", x = "", y = "", split = "" },
    { query = "chargeback", title = "Business unit / cost center chargeback", chart = "", x = "", y = "", split = "" },
    { query = "applications", title = "Application subscription attribution", chart = "", x = "", y = "", split = "" },
    { query = "request-health", title = "Request errors and latency details", chart = "", x = "", y = "", split = "" },
    { query = "event-hub-health", title = "Event Hub ingress / throttling / delivery failures", chart = "", x = "", y = "", split = "" },
    { query = "usage-unknown", title = "Unknown provider usage — unpriced, never zero", chart = "", x = "", y = "", split = "" },
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
              **Monthly USD budgets are approximate soft caps.** Redis is the live source for cached budget configuration and monthly spend. Every configured user, team and department limit is checked before dispatch; concurrent in-flight calls can overshoot. Only finalized provider usage updates spend. Cached input is a subset of input, not additional tokens. Unknown usage is unpriced, never reported as zero.

              APIM HTTP outcomes, Function budget decisions and finalized accounting are separate stages. A 2xx or admitted request is not proof of finalized usage. Blocks are requests, not measured tokens; no provider usage exists for a request rejected before inference. Cache charts show provider prompt-cache reads, not APIM response caching.

              Token stacks contain disjoint uncached input, cached input and output. Cache percentage is cached input divided by all input tokens, not the percentage of requests with a cache hit. Lifecycle series overlap: admitted includes finalized and unknown outcomes. No terminal observed after five minutes is an investigation signal, not proof of lost billing.

              Month-to-date spend uses UTC month start; other activity views follow the dashboard time picker. Budget utilization is the latest observed monthly counter, not a live Redis read, and may exceed 100% because these are soft caps. User references are opaque; subscription IDs attribute applications, not people.

              This dashboard and the portal share the exact persisted KQL below. Traces can be sampled or delayed. Usage records and request context are persisted to Table Storage by a bounded process-local background task, not awaited by inference. Host restarts, failures or queue saturation can permanently lose history. Redis loss may reset live spend; chargeback reports include only persisted usage and may differ from live counters. Event Hub delivery is best effort, unsampled by APIM, and never retried. An event proves Redis acceptance, not Table persistence. Namespace diagnostics and APIM logger failures show operational delivery health.
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
            { name = "ControlType", value = tile.chart == "" ? "AnalyticsGrid" : "AnalyticsChart", isOptional = true },
            { name = "PartTitle", value = tile.title, isOptional = true },
            { name = "IsQueryContainTimeRange", value = contains(["monthly-spend", "budgets"], tile.query), isOptional = true },
            { name = "SpecificChart", value = tile.chart, isOptional = true },
            { name = "Dimensions", value = {
              xAxis = {
                name = tile.x
                type = contains(["gateway-traffic", "token-trend", "function-latency"], tile.query) ? "datetime" : "string"
              }
              yAxis = [{
                name = tile.y
                type = contains(["cache-hit", "function-latency", "monthly-spend", "budgets"], tile.query) ? "real" : "long"
              }]
              splitBy = tile.split == "" ? [] : [{ name = tile.split, type = "string" }]
            }, isOptional = true },
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
