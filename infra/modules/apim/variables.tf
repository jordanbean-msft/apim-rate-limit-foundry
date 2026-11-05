variable "name" {
  description = "APIM CAF name."
  type        = string
}
variable "resource_group_name" {
  description = "Existing resource group."
  type        = string
}
variable "location" {
  description = "Resource location."
  type        = string
}
variable "tags" {
  description = "Resource tags."
  type        = map(string)
}
variable "public_network_access_enabled" {
  description = "Explicit public development opt-in."
  type        = bool
}
variable "subnet_id" {
  description = "Existing APIM internal VNet subnet."
  type        = string
}
variable "config" {
  description = "Gateway capability, identity and conservative admission settings."
  type = object({
    sku_name                    = string
    publisher_name              = string
    publisher_email             = string
    client_audiences            = list(string)
    subscription_tenant_mapping = map(string)
    burst_calls                 = number
    burst_seconds               = number
    max_body_bytes              = number
    max_output_tokens           = number
    max_document_pages          = number
    max_language_characters     = number
    send_request_timeout        = number
    enable_optional_llm_policy  = bool
    llm_policy_verified         = bool
    llm_tokens_per_minute       = number
  })
}
variable "identity" {
  description = "Gateway managed identity."
  type        = object({ id = string, client_id = string, principal_id = string })
}
variable "authority" {
  description = "Cloud Entra authority."
  type        = string
}
variable "tenant_id" {
  description = "Validated single tenant."
  type        = string
}
variable "function_url" {
  description = "Limiter host root; Function routes use /api."
  type        = string
}
variable "api_audience" {
  description = "Managed identity token resource."
  type        = string
}
variable "web_url" {
  description = "Only allowed browser origin."
  type        = string
}
variable "ai" {
  description = "Enabled exact AI backend references."
  type = map(object({
    id            = string
    endpoint      = string
    audience      = string
    model         = string
    api_version   = string
    price_version = string
    created       = bool
  }))
}
variable "application_insights_id" {
  description = "Native APIM telemetry resource."
  type        = string
}
variable "instrumentation_key" {
  description = "APIM logger credential."
  type        = string
  sensitive   = true
}
