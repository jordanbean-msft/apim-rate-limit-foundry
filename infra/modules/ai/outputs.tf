output "backends" {
  description = "Enabled exact endpoints, resource identities, and pricing model deployment."
  value = merge({ for key, config in local.enabled : key => {
    id            = config.create ? azurerm_cognitive_account.this[key].id : config.resource_id
    endpoint      = trimsuffix(config.create ? local.created_endpoints[key] : config.endpoint, "/")
    audience      = config.audience
    model         = config.deployment_name
    api_version   = config.api_version
    price_version = config.price_version
    created       = config.create
    api_protocol  = key == "foundry" ? "openai-chat" : ""
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
output "stream_role_assignments" {
  description = "Resource-and-role deduplicated AI access granted only to the streaming Function."
  value = { for key, binding in azurerm_role_assignment.stream : key => {
    scope = binding.scope, role = binding.role_definition_name, principal_id = binding.principal_id
  } }
}
output "managed_deployments" {
  description = "Safe managed deployment/version/capacity inventory, separate from the preserved legacy deployment."
  value = { for alias, deployment in azurerm_cognitive_deployment.managed : alias => {
    name     = deployment.name, model_name = deployment.model[0].name, model_version = deployment.model[0].version,
    capacity = deployment.sku[0].capacity
  } }
}
