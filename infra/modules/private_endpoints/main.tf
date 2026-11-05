resource "azurerm_private_endpoint" "this" {
  for_each            = var.targets
  name                = "${basename(each.value.id)}-${each.key}-pe"
  resource_group_name = var.resource_group_name
  location            = var.location
  subnet_id           = var.subnet_id
  private_service_connection {
    name                           = "${basename(each.value.id)}-${each.key}-psc"
    private_connection_resource_id = each.value.id
    subresource_names              = [each.value.group]
    is_manual_connection           = false
  }
  lifecycle {
    ignore_changes = [private_dns_zone_group]
  }
  tags = var.tags
}
