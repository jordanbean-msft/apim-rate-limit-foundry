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
variable "subnet_id" {
  description = "Existing private endpoint subnet."
  type        = string
}
variable "targets" {
  description = "Private link targets. Referenced AI resources require operator-provided private routing."
  type        = map(object({ id = string, group = string }))
}
