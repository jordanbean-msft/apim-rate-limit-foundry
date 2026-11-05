output "backends" {
  description = "Enabled exact endpoints, resource identities, and pricing model deployment."
  value = merge({ for key, config in local.enabled : key => {
    id                   = config.create ? azurerm_cognitive_account.this[key].id : config.resource_id
    endpoint             = trimsuffix(config.create ? azurerm_cognitive_account.this[key].endpoint : config.endpoint, "/")
    audience             = config.audience
    model                = config.deployment_name
    api_version          = config.api_version
    price_version        = config.price_version
    created              = config.create
    api_protocol         = key == "foundry" ? "openai-chat" : ""
    context_input_tokens = 0
    anthropic_version    = ""
    } }, { for key, protocol in local.protocol_backends : key => merge(protocol, {
      endpoint = trimsuffix(protocol.endpoint, "/"), created = false
  }) })
}
output "protocol_role_assignment_ids" {
  description = "Deduplicated additional assignments; existing AI role bindings are reused."
  value       = { for key, binding in azurerm_role_assignment.protocol : key => binding.id }
}
output "gateway_role_assignments" {
  description = "Canonical existing-backend assignments, including names for shared-scope auditing."
  value = { for key, binding in azurerm_role_assignment.gateway : key => {
    name = binding.name, scope = binding.scope, role = binding.role_definition_name
  } }
}
