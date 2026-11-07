variable "name" {
  description = "APIM CAF name."
  type        = string
}
variable "resource_group_name" {
  description = "Existing resource group."
  type        = string
}
variable "resource_group_id" {
  description = "Existing resource group ARM scope."
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
    sku_name                       = string
    publisher_name                 = string
    publisher_email                = string
    client_audiences               = list(string)
    burst_calls                    = number
    burst_seconds                  = number
    max_body_bytes                 = number
    max_output_tokens              = number
    max_document_pages             = number
    max_language_characters        = number
    send_request_timeout           = number
    enable_optional_llm_policy     = bool
    llm_policy_verified            = bool
    llm_tokens_per_minute          = number
    diagnostic_sampling_percentage = number
    openai_byte_tokenizer_verified = bool
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
    id                   = string
    endpoint             = string
    audience             = string
    model                = string
    api_version          = string
    price_version        = string
    created              = bool
    api_protocol         = string
    context_input_tokens = number
    anthropic_version    = string
  }))
}
variable "route_backends" {
  description = "Protocol API sentinels required by the effective registry; never used as implicit model defaults."
  type = map(object({
    id                   = string
    endpoint             = string
    audience             = string
    model                = string
    api_version          = string
    price_version        = string
    created              = bool
    api_protocol         = string
    context_input_tokens = number
    anthropic_version    = string
  }))
}
variable "model_registry" {
  description = "Effective protocol:alias allowlist shared by APIM and both Function hosts."
  type = map(object({
    api_protocol      = string
    endpoint          = string
    path              = string
    model             = string
    audience          = string
    api_version       = string
    anthropic_version = string
    price_version     = string
    max_input_tokens  = number
    max_output_tokens = number
  }))
}
variable "legacy_defaults" {
  description = "Explicit legacy default aliases only; additional model entries never become implicit defaults."
  type        = map(string)
}
variable "max_input_tokens" {
  description = "Shared Function input admission bound, not a universal tokenizer assumption."
  type        = number
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
variable "streaming_enabled" {
  description = "Relay admitted streaming requests through the trusted observer."
  type        = bool
}
variable "stream_url" {
  description = "Fixed dedicated HTTP streams Function origin."
  type        = string
}
variable "applications" {
  description = "Stable product-scoped subscriptions and safe inference application metadata."
  type = object({
    inference = map(object({
      tenant_id    = string
      display_name = string
    }))
    portal = object({
      subscription_id = string
      display_name    = string
    })
  })
}
