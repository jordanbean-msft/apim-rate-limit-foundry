variable "resource_token" {
  description = "Deterministic resource naming token."
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
variable "tenant_id" {
  description = "Entra tenant."
  type        = string
}
variable "deployer_object_id" {
  description = "Initial administrator principal."
  type        = string
}
variable "portal_redirect_uri" {
  description = "Cloud-specific portal origin."
  type        = string
}
variable "config" {
  description = "Entra role membership and propagation wait."
  type = object({
    admin_object_ids          = set(string)
    reader_object_ids         = set(string)
    propagation_wait_duration = string
  })
}
