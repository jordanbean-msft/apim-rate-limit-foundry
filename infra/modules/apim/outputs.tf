output "id" {
  description = "Gateway resource."
  value       = azapi_resource.this.id
}
output "gateway_url" {
  description = "Cloud-aware gateway URL supplied by ARM."
  value       = azapi_resource.this.output.properties.gatewayUrl
}
output "llm_routes" {
  description = "Only enabled LLM operations and their pinned protocol/model contracts."
  value = { for key, backend in var.ai : key => {
    path              = "/${key == "responses" ? "foundry" : key}${local.ai_paths[key]}"
    api_protocol      = backend.api_protocol
    model             = backend.model
    backend_path      = local.backend_paths[key]
    api_version       = backend.api_version
    anthropic_version = backend.anthropic_version
  } if backend.api_protocol != "" }
}
