resource "azurerm_storage_account" "this" {
  name                            = var.name
  resource_group_name             = var.resource_group_name
  location                        = var.location
  account_tier                    = var.config.account_tier
  account_replication_type        = var.config.account_replication_type
  account_kind                    = "StorageV2"
  min_tls_version                 = "TLS1_2"
  shared_access_key_enabled       = false
  default_to_oauth_authentication = true
  allow_nested_items_to_be_public = false
  public_network_access_enabled   = var.public_network_access_enabled
  tags                            = var.tags
}
resource "azurerm_storage_table" "this" {
  name               = var.config.table_name
  storage_account_id = azurerm_storage_account.this.id
  depends_on         = [azurerm_role_assignment.deployer]
}
resource "azurerm_role_assignment" "function" {
  for_each = toset([
    "Storage Blob Data Owner", "Storage Queue Data Contributor",
    "Storage Table Data Contributor", "Storage Account Contributor"
  ])
  name                 = uuidv5("dns", "${azurerm_storage_account.this.id}/${var.principal_id}/${each.key}")
  scope                = azurerm_storage_account.this.id
  role_definition_name = each.key
  principal_id         = var.principal_id
}
resource "azurerm_role_assignment" "deployer" {
  name                 = uuidv5("dns", "${azurerm_storage_account.this.id}/${var.deployer_principal_id}/table")
  scope                = azurerm_storage_account.this.id
  role_definition_name = "Storage Table Data Contributor"
  principal_id         = var.deployer_principal_id
}
