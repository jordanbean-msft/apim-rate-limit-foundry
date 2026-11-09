variable "resource_token" {
  description = "Deterministic resource naming token."
  type        = string
}
variable "resource_group_name" {
  description = "Existing resource group."
  type        = string
}
variable "azure_cloud" {
  description = "Selected cloud for created Foundry accounts' OpenAI-compatible inference origins."
  type        = string
  validation {
    condition     = contains(["commercial", "government"], var.azure_cloud)
    error_message = "Use commercial or government; no endpoint cloud fallback is allowed."
  }
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
  description = "Explicit AI backend deployment/reference configuration."
  type = map(object({
    enabled             = bool
    create              = bool
    resource_id         = string
    endpoint            = string
    audience            = string
    sku_name            = string
    location            = string
    deployment_name     = string
    model_name          = string
    model_version       = string
    deployment_sku      = string
    deployment_capacity = number
    api_version         = string
    price_version       = string
  }))
}
variable "gateway_principal_id" {
  description = "APIM identity object ID."
  type        = string
}
variable "protocols" {
  description = "Explicit optional protocol references; these resources are never auto-created."
  type = object({
    responses = object({
      enabled                   = bool
      capability_verified       = bool
      government_verified       = bool
      byte_tokenizer_verified   = bool
      private_endpoint_verified = bool
      resource_id               = string
      endpoint                  = string
      audience                  = string
      location                  = string
      deployment_name           = string
      price_version             = string
      role_definition_name      = string
      api_version               = string
    })
  })
}
variable "llm_models" {
  description = "Additional referenced model deployments and their APIM/stream identity grants."
  type = map(object({
    api_protocol              = string
    resource_id               = string
    endpoint                  = string
    audience                  = string
    location                  = string
    deployment_name           = string
    price_version             = string
    max_input_tokens          = number
    max_output_tokens         = number
    role_definition_name      = string
    capability_verified       = bool
    government_verified       = bool
    byte_tokenizer_verified   = bool
    private_endpoint_verified = bool
    api_version               = string
  }))
}
variable "streaming_enabled" {
  description = "Grant the trusted stream observer access only when deployed."
  type        = bool
}
variable "function_principal_id" {
  description = "Shared limiter and stream Function workload principal."
  type        = string
}
variable "managed_deployments" {
  description = "Additional managed OpenAI deployments; the existing foundry deployment is preserved separately."
  type = map(object({
    model_name          = string
    model_version       = string
    deployment_sku      = string
    deployment_capacity = number
  }))
}
