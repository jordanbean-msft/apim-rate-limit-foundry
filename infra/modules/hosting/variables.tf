variable "names" {
  description = "CAF generated service names."
  type        = map(string)
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
variable "network" {
  description = "Existing integration subnets."
  type = object({
    functions_subnet_id = string
    web_subnet_id       = string
  })
}
variable "config" {
  description = "Explicit portable compute configuration."
  type = object({
    functions_sku               = string
    web_sku                     = string
    python_version              = string
    node_version                = string
    function_always_on          = bool
    web_always_on               = bool
    stream_always_on            = bool
    function_workers            = number
    web_workers                 = number
    minimum_tls_version         = string
    cors_origins                = list(string)
    max_input_tokens            = number
    allowed_client_applications = list(string)
    telemetry_sampling_ratio    = number
    log_retention_days          = number
    log_disk_quota_mb           = number
  })
  validation {
    condition     = var.config.node_version == "24-lts"
    error_message = "Use the verified Node 24 LTS App Service runtime."
  }
}
variable "function_identity" {
  description = "Function workload identity."
  type        = object({ id = string, client_id = string, principal_id = string })
}
variable "web_identity" {
  description = "Web workload identity."
  type        = object({ id = string, client_id = string, principal_id = string })
}
variable "storage_account_name" {
  description = "Identity-authenticated host storage."
  type        = string
}
variable "application_insights_connection_string" {
  description = "Native function telemetry integration."
  type        = string
  sensitive   = true
}
variable "function_settings" {
  description = "Backend runtime settings."
  type        = map(string)
}
variable "web_settings" {
  description = "Portal runtime settings."
  type        = map(string)
  sensitive   = true
}
variable "api_client_id" {
  description = "Easy Auth app registration."
  type        = string
}
variable "web_client_id" {
  description = "Single-tenant portal registration shared by browser PKCE and native web sign-in."
  type        = string
}
variable "api_audience" {
  description = "Easy Auth API URI audience."
  type        = string
}
variable "authority" {
  description = "Cloud-specific Entra authority."
  type        = string
}
variable "tenant_id" {
  description = "Single Entra tenant."
  type        = string
}
variable "streaming_enabled" {
  description = "Deploy the separate HTTP streams host on the existing Function plan."
  type        = bool
}
variable "stream_settings" {
  description = "Fixed backend map and bounded stream observer settings."
  type        = map(string)
}
