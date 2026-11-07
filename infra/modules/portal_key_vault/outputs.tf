output "id" {
  description = "Portal-only Key Vault resource."
  value       = azurerm_key_vault.this.id
}
output "secret_uri" {
  description = "Versionless secret URI for managed-identity App Service references; contains no key value."
  value       = azurerm_key_vault_secret.portal.versionless_id
}
