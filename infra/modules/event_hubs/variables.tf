variable "resource_token" {
  description = "Deterministic naming token."
  type        = string
}
variable "resource_group_name" {
  description = "Existing resource group."
  type        = string
}
variable "location" {
  description = "Explicit namespace region."
  type        = string
}
variable "tags" {
  description = "Resource tags."
  type        = map(string)
}
variable "public_network_access_enabled" {
  description = "Public access opt-in; otherwise use the private endpoint."
  type        = bool
}
variable "private_endpoint_subnet_id" {
  description = "Existing endpoint subnet with DINE-managed DNS."
  type        = string
}
variable "workspace_id" {
  description = "Shared Log Analytics workspace resource ID."
  type        = string
}
variable "gateway_principal_id" {
  description = "Only APIM receives the Event Hubs sender role."
  type        = string
}
variable "config" {
  description = "Explicit namespace/hub sizing, retention and RBAC propagation."
  type = object({
    sku                       = string
    capacity                  = number
    partition_count           = number
    message_retention         = number
    minimum_tls_version       = string
    propagation_wait_duration = string
  })
  validation {
    condition = (
      var.config.sku == "Standard" &&
      var.config.capacity >= 1 && var.config.capacity <= 40 &&
      floor(var.config.capacity) == var.config.capacity &&
      var.config.partition_count >= 1 && var.config.partition_count <= 32 &&
      floor(var.config.partition_count) == var.config.partition_count &&
      var.config.message_retention >= 1 && var.config.message_retention <= 7 &&
      floor(var.config.message_retention) == var.config.message_retention &&
      var.config.minimum_tls_version == "1.2" &&
      can(regex("^[0-9]+[smh]$", var.config.propagation_wait_duration))
    )
    error_message = "Use Standard, 1..40 throughput units, 1..32 partitions, 1..7 retention days, TLS 1.2 and an explicit propagation duration."
  }
}
variable "azure_cloud" {
  description = "Explicit commercial/government cloud for the namespace DNS suffix."
  type        = string
  validation {
    condition     = contains(["commercial", "government"], var.azure_cloud)
    error_message = "Use commercial or government; no endpoint cloud fallback is allowed."
  }
}
