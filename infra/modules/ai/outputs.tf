output "backends" {
  description = "Enabled exact endpoints, resource identities, and pricing model deployment."
  value = { for key, config in local.enabled : key => {
    id            = config.create ? azurerm_cognitive_account.this[key].id : config.resource_id
    endpoint      = trimsuffix(config.create ? azurerm_cognitive_account.this[key].endpoint : config.endpoint, "/")
    audience      = config.audience
    model         = config.deployment_name
    api_version   = config.api_version
    price_version = config.price_version
    created       = config.create
  } }
}
