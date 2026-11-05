variable "resource_token" {
  description = "Deterministic resource naming token."
  type        = string
}
variable "resource_group_name" {
  description = "Existing resource group."
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
    anthropic = object({
      enabled                   = bool
      capability_verified       = bool
      private_endpoint_verified = bool
      hard_input_cap_verified   = bool
      input_cap_evidence        = string
      context_input_tokens      = number
      resource_id               = string
      endpoint                  = string
      audience                  = string
      location                  = string
      deployment_name           = string
      price_version             = string
      anthropic_version         = string
      role_definition_name      = string
    })
  })
}
