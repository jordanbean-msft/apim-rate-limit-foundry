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
  dashboard_tiles = [
    { query = "admissions", title = "Admissions by service / protocol", chart = "Line" },
    { query = "denials", title = "Recent custom denials and policies", chart = "" },
    { query = "gateway-429", title = "APIM 429 origin (correlation join)", chart = "" },
    { query = "policy-pressure", title = "Policy demand, remaining and limit", chart = "" },
    { query = "cost-liability", title = "Admission cohort USD: settled or pending, never both", chart = "" },
    { query = "cache-service-units", title = "Deduplicated settlement cache tokens and service units", chart = "" },
    { query = "latency", title = "Reserve / settle request latency", chart = "" },
    { query = "dependency-failures", title = "Redis / Table dependency failures", chart = "" },
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
            subtitle       = "Operational telemetry — not a billing report or durable ledger"
            markdownSource = 1
            content        = <<-MARKDOWN
              **Default: last 24 hours.** Change the dashboard time picker to filter every log tile.

              Admission uses conservative estimates; actual settlement can refund the bound. USD uses one cost per reservation, not the sum of overlapping policy charges. Cache/service units use the latest settlement per reservation. Retries are deduplicated; latency/dependencies count physical attempts.

              Ingestion delay, sampling, missing traces and admission/settlement on opposite sides of the selected window can leave apparent pending liabilities or unmatched 429s. Historical fields may be blank. A missing custom decision is **not proof** of native throttling. Use the durable ledger for authoritative accounting.
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
                xAxis       = { name = "TimeGenerated", type = "datetime" }
                yAxis       = [{ name = "Reservations", type = "long" }]
                splitBy     = [{ name = "Series", type = "string" }]
                aggregation = "Sum"
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
