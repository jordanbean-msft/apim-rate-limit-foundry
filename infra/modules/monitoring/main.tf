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
  # Queries deliberately omit time predicates: the dashboard supplies the query timespan.
  dashboard_charts = [
    {
      query    = "admissions", title = "Admissions over time by service / protocol", chart = "Line"
      x_axis   = { name = "TimeGenerated", type = "datetime" }, y_axis = { name = "Reservations", type = "long" }
      split_by = { name = "Series", type = "string" }, aggregation = "Sum"
    },
    {
      query    = "decision-outcomes", title = "Allow vs deny decisions", chart = "Pie"
      x_axis   = { name = "Outcome", type = "string" }, y_axis = { name = "Reservations", type = "long" }
      split_by = null, aggregation = "Sum"
    },
    {
      query    = "throttling-trend", title = "Custom throttling over time", chart = "StackedColumn"
      x_axis   = { name = "TimeGenerated", type = "datetime" }, y_axis = { name = "DeniedRequests", type = "long" }
      split_by = { name = "Service", type = "string" }, aggregation = "Sum"
    },
    {
      query    = "cost-trend", title = "Effective USD over time: actual vs conservative", chart = "Line"
      x_axis   = { name = "TimeGenerated", type = "datetime" }, y_axis = { name = "EffectiveUSD", type = "real" }
      split_by = { name = "Accounting", type = "string" }, aggregation = "Sum"
    },
    {
      query    = "policy-denials", title = "Blocking policies and rate-limit units", chart = "Column"
      x_axis   = { name = "Policy", type = "string" }, y_axis = { name = "DeniedRequests", type = "long" }
      split_by = { name = "Metric", type = "string" }, aggregation = "Sum"
    },
    {
      query    = "token-composition", title = "Actual settled input / cache / output tokens", chart = "StackedColumn"
      x_axis   = { name = "TimeGenerated", type = "datetime" }, y_axis = { name = "Tokens", type = "long" }
      split_by = { name = "Series", type = "string" }, aggregation = "Sum"
    },
    {
      query    = "latency-trend", title = "Reserve / settle latency over time (p50 / p95 ms)", chart = "Line"
      x_axis   = { name = "TimeGenerated", type = "datetime" }, y_axis = { name = "Milliseconds", type = "real" }
      split_by = { name = "Series", type = "string" }, aggregation = "Average"
    },
    {
      query    = "caller-denials", title = "Application subscriptions hitting limits by service / model", chart = "StackedColumn"
      x_axis   = { name = "SubscriptionId", type = "string" }, y_axis = { name = "DeniedRequests", type = "long" }
      split_by = { name = "ServiceModel", type = "string" }, aggregation = "Sum"
    },
    {
      query    = "caller-costs", title = "Application subscription USD by service / model", chart = "StackedColumn"
      x_axis   = { name = "SubscriptionId", type = "string" }, y_axis = { name = "EffectiveUSD", type = "real" }
      split_by = { name = "ServiceModel", type = "string" }, aggregation = "Sum"
    },
    {
      query    = "gateway-caller-429", title = "Gateway 429s by application subscription and origin", chart = "StackedColumn"
      x_axis   = { name = "SubscriptionId", type = "string" }, y_axis = { name = "Responses", type = "long" }
      split_by = { name = "Origin", type = "string" }, aggregation = "Sum"
    },
    {
      query    = "streaming-outcomes", title = "Streaming accounting: actual vs conservative", chart = "StackedColumn"
      x_axis   = { name = "TimeGenerated", type = "datetime" }, y_axis = { name = "Reservations", type = "long" }
      split_by = { name = "Accounting", type = "string" }, aggregation = "Sum"
    },
    {
      query    = "streaming-economics", title = "Streaming USD: reserved, effective and released liability", chart = "Line"
      x_axis   = { name = "TimeGenerated", type = "datetime" }, y_axis = { name = "USD", type = "real" }
      split_by = { name = "Series", type = "string" }, aggregation = "Sum"
    },
    {
      query    = "streaming-cache", title = "Actual streaming input / cache / output tokens", chart = "StackedColumn"
      x_axis   = { name = "TimeGenerated", type = "datetime" }, y_axis = { name = "Tokens", type = "long" }
      split_by = { name = "Series", type = "string" }, aggregation = "Sum"
    },
  ]
  dashboard_tiles = concat(local.dashboard_charts, [
    for tile in [
      { query = "denials", title = "Recent custom denials and policies" },
      { query = "gateway-429", title = "APIM 429 origin (correlation join)" },
      { query = "policy-pressure", title = "Subscription limits, remaining and demand (last decisions)" },
      { query = "cost-liability", title = "Admission cohort USD: settled or pending, never both" },
      { query = "cache-service-units", title = "Deduplicated settlement cache tokens and service units" },
      { query = "latency", title = "Reserve / settle request latency" },
      { query = "dependency-failures", title = "Redis / Table dependency failures" },
      { query = "callers", title = "Application subscription, service and model attribution" },
      { query = "streaming-status", title = "Streaming settlements, cache tokens and pending reasons" },
    ] : merge(tile, { chart = "", x_axis = null, y_axis = null, split_by = null, aggregation = null })
  ])
  dashboard_parts = merge(
    {
      "0" = {
        position = { x = 0, y = 0, colSpan = 18, rowSpan = 3 }
        metadata = {
          inputs = []
          type   = "Extension/HubsExtension/PartType/MarkdownPart"
          settings = { content = { settings = {
            title          = "Granular AI rate limiter"
            subtitle       = "Operational telemetry — not a billing report or durable ledger"
            markdownSource = 1
            content        = <<-MARKDOWN
              **Default: last 24 hours.** Thirteen charts show decisions, throttling, caller costs/denials, streaming reconciliation, cache tokens and latency. Nine detail tables follow. Change the dashboard time picker to filter every tile; trend bins are one minute.

              Admission uses conservative estimates; actual settlement can refund the bound. USD uses one cost per reservation, not the sum of overlapping policy charges. Cache/service units use the latest settlement per reservation. Retries are deduplicated; latency/dependencies count physical attempts.

              Applications are identified by their stable APIM subscription ID, never by primary/secondary key values or the signed-in user. Rotate keys without resetting an application's allowance. Map IDs to labels in the portal's application-subscription view; the top-20 charts group by subscription and model. Both Entra authentication and a product subscription key are required.

              Application-accounting tiles exclude legacy user-based telemetry without subscription IDs; latency/dependency tiles still count all physical attempts. Native gateway 429s fall back to APIM's non-secret subscription ID when an identity trace is missing. Remaining/limit values are last-decision observations, not live Redis balances.

              Costs are per admission-minute, not cumulative or an Azure invoice. Streaming reserve/effective/refund lines are comparisons, not additive spend. Token composition includes actual, non-estimated LLM settlements only. A request blocked by multiple rules appears in each binding policy's column. Ingestion delay, sampling and window boundaries can leave apparent pending liabilities or unmatched 429s. A missing custom decision is **not proof** of native throttling. Use the durable ledger for authoritative accounting.
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
          inputs = concat(
            [
              { name = "Scope", value = { resourceIds = [azurerm_log_analytics_workspace.law.id] }, isOptional = true },
              { name = "PartId", value = uuidv5("url", "${var.resource_token}/rate-limiter/${tile.query}"), isOptional = true },
              { name = "Version", value = "2.0", isOptional = true },
              { name = "TimeRange", isOptional = true },
              { name = "Query", value = file("${path.module}/queries/${tile.query}.kql"), isOptional = true },
              { name = "ControlType", value = tile.chart == "" ? "AnalyticsGrid" : "FrameControlChart", isOptional = true },
              { name = "PartTitle", value = tile.title, isOptional = true },
              { name = "IsQueryContainTimeRange", value = false, isOptional = true },
            ],
            [for input in [
              { name = "SpecificChart", value = tile.chart, isOptional = true },
              { name = "Dimensions", value = {
                xAxis       = tile.x_axis
                yAxis       = [tile.y_axis]
                splitBy     = tile.split_by == null ? [] : [tile.split_by]
                aggregation = tile.aggregation
              }, isOptional = true },
              { name = "LegendOptions", value = { isEnabled = true, position = "Bottom" }, isOptional = true },
            ] : input if tile.chart != ""]
          )
          settings = { content = { PartTitle = tile.title, IsQueryContainTimeRange = false } }
        }
      }
    }
  )
}

# Portal dashboards have no native diagnostic settings or Application Insights integration.
# This resource only stores tile configuration; existing workspace telemetry is queried in place.
resource "azurerm_portal_dashboard" "rate_limiter" {
  name                = azurecaf_name.dashboard.result
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = merge(var.tags, { "hidden-title" = "Granular AI rate limiter" })
  dashboard_properties = jsonencode({
    lenses = { "0" = { order = 0, parts = local.dashboard_parts } }
    metadata = { model = {
      timeRange = {
        value = { relative = { duration = 24, timeUnit = 1 } }
        type  = "MsPortalFx.Composition.Configuration.ValueTypes.TimeRange"
      }

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
