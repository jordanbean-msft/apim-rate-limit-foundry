variable "name" {
  description = "Redis CAF name."
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
variable "azure_cloud" {
  description = "Cloud selects Managed Redis or Government Cache."
  type        = string
}
variable "config" {
  description = "Explicit Redis sizing and transport."
  type = object({
    managed_sku         = string
    high_availability   = bool
    government_capacity = number
    minimum_tls_version = string
    token_scope         = string
    inspection_enabled  = bool
  })
}
variable "inspection_principal_id" {
  description = "Operator object ID for explicitly enabled read-only Redis inspection."
  type        = string
}
variable "principal_id" {
  description = "Function identity object ID."
  type        = string
}
