data "azurerm_resource_group" "rg" {
  name = var.azure.resource_group_name
}

data "azurerm_client_config" "current" {}

locals {
  prefix             = "${var.naming.project_name}-${var.azure.environment_name}"
  resource_token_sha = base64encode(sha256("${var.azure.location}${data.azurerm_client_config.current.subscription_id}${var.azure.resource_group_name}"))
  resource_token     = substr(join("", regexall("[a-z0-9]", lower(local.resource_token_sha))), 0, 13)

  default_tags = merge(
    {
      project     = var.naming.project_name
      environment = var.azure.environment_name
      managed_by  = "terraform"
    },
    var.tags
  )
}

module "monitoring" {
  source = "./modules/monitoring"

  resource_token      = local.resource_token
  resource_group_name = data.azurerm_resource_group.rg.name
  location            = data.azurerm_resource_group.rg.location
  tags                = local.default_tags
}
