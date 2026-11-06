mock_provider "azurerm" {
  mock_resource "azurerm_managed_redis" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/sample-rg/providers/Microsoft.Cache/redisEnterprise/sample"
    }
  }
}
mock_provider "azapi" {}

variables {
  name                          = "sample"
  resource_group_name           = "sample-rg"
  location                      = "eastus2"
  tags                          = {}
  public_network_access_enabled = true
  principal_id                  = "00000000-0000-0000-0000-000000000002"
  inspection_principal_id       = "00000000-0000-0000-0000-000000000003"
  config = {
    managed_sku         = "Balanced_B1"
    high_availability   = true
    government_capacity = 1
    minimum_tls_version = "1.2"
    token_scope         = "https://redis.azure.com/.default"
    inspection_enabled  = true
  }
}
run "commercial_read_only_inspection" {
  command = plan
  module {
    source = "./modules/redis"
  }
  variables {
    azure_cloud = "commercial"
  }
  assert {
    condition     = azapi_resource.inspector_commercial[0].body.properties.accessString == "+@read +ping +info +scan +client|setinfo ~{limiter}:*"
    error_message = "Commercial inspection must be read-only and scoped to limiter keys."
  }
  assert {
    condition     = length(azurerm_redis_cache_access_policy_assignment.inspector_government) == 0
    error_message = "Commercial must not assign a Government role."
  }
}
run "government_read_only_inspection" {
  command = plan
  module {
    source = "./modules/redis"
  }
  variables {
    azure_cloud = "government"
    location    = "usgovvirginia"
  }
  assert {
    condition     = azurerm_redis_cache_access_policy_assignment.inspector_government[0].access_policy_name == "Data Reader"
    error_message = "Government inspection must not grant data writes."
  }
}
