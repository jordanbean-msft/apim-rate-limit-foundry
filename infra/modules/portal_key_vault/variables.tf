variable "resource_token" {
  description = "Deterministic resource naming token."
  type        = string
}
variable "resource_group_name" {
  description = "Existing resource group."
  type        = string
}
variable "location" {
  description = "Deployment location."
  type        = string
}
variable "tags" {
  description = "Resource tags."
  type        = map(string)
}
variable "tenant_id" {
  description = "Validated Entra tenant."
  type        = string
}
variable "public_network_access_enabled" {
  description = "Explicit public network opt-in, shared with application networking."
  type        = bool
}
variable "private_endpoint_subnet_id" {
  description = "Existing private endpoint subnet; DNS is managed by Azure policy."
  type        = string
}
variable "deployer_principal_id" {
  description = "Initial IaC secret writer; requires protected remote state."
  type        = string
}
variable "web_principal_id" {
  description = "Dedicated portal identity; read-only secret access."
  type        = string
}
variable "workspace_id" {
  description = "Shared Log Analytics diagnostic destination."
  type        = string
}
variable "config" {
  description = "Explicit Key Vault retention, SKU, protection and RBAC propagation settings."
  type = object({
    sku_name                   = string
    soft_delete_retention_days = number
    purge_protection_enabled   = bool
    propagation_wait_duration  = string
  })
}
variable "portal_subscription_key" {
  description = "APIM requires a native subscription key in addition to Entra; store only in Key Vault and protected Terraform state."
  type        = string
  sensitive   = true
}
