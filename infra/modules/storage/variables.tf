variable "name" {
  description = "Storage account CAF name."
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
variable "config" {
  description = "Durable storage configuration."
  type = object({
    account_tier             = string
    account_replication_type = string
    table_name               = string
  })
}
variable "principal_id" {
  description = "Function identity object ID."
  type        = string
}
variable "deployer_principal_id" {
  description = "Deployer identity for Table provisioning/bootstrap."
  type        = string
}
