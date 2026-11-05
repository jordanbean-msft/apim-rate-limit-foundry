# Variables sourced from Azure Developer CLI (azd) environment.
# These are populated from azd environment variables via infra/main.tfvars.json
# using ${VAR_NAME} placeholders.
# For local development without azd, set them in terraform.local.tfvars.json.

variable "azure" {
  description = "Core Azure environment values sourced from azd environment variables."
  type = object({
    subscription_id     = string
    tenant_id           = string
    location            = string
    environment_name    = string
    resource_group_name = string
    principal_id        = string
  })

  validation {
    condition     = can(regex("^[a-z0-9]+(-[a-z0-9]+)*$", var.azure.environment_name))
    error_message = "azure.environment_name must use lowercase letters, numbers, and internal hyphens only."
  }
}

variable "naming" {
  description = "Naming configuration for project resources."
  type = object({
    project_name = optional(string, "tmplrepo")
  })
  default = {}

  validation {
    condition     = can(regex("^[a-z0-9]{1,8}$", var.naming.project_name))
    error_message = "naming.project_name must be 1-8 lowercase alphanumeric characters."
  }
}

variable "monitoring" {
  description = "Monitoring configuration values."
  type        = object({})
  default     = {}
}

variable "tags" {
  description = "Additional tags to merge onto all resources."
  type        = map(string)
  default     = {}
}
