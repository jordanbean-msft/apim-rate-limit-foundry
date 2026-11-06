variable "resource_token" {
  description = "Token used to generate unique resource names."
  type        = string
}

variable "resource_group_name" {
  description = "Name of the resource group."
  type        = string
}

variable "location" {
  description = "Azure region for resources."
  type        = string
}

variable "tags" {
  description = "Tags to apply to resources."
  type        = map(string)
  default     = {}
}
variable "config" {
  description = "Explicit Log Analytics configuration."
  type = object({
    sku               = string
    retention_in_days = number
  })
}

variable "azure_cloud" {
  description = "Azure cloud used to select the dashboard portal endpoint."
  type        = string
  validation {
    condition     = contains(["commercial", "government"], var.azure_cloud)
    error_message = "azure_cloud must be commercial or government."
  }
}
