terraform {
  required_version = ">= 1.9"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.13"
    }
    azapi = {
      source  = "Azure/azapi"
      version = "~> 2.13"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3.10"
    }
    azurecaf = {
      source  = "aztfmod/azurecaf"
      version = "~> 2.0"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.14"
    }
  }
  backend "azurerm" {}
}

provider "azurerm" {
  subscription_id     = var.azure.subscription_id
  tenant_id           = var.azure.tenant_id
  environment         = var.azure_cloud == "AzureUSGovernment" ? "usgovernment" : "public"
  storage_use_azuread = true
  features {
    key_vault {
      purge_soft_delete_on_destroy    = false
      recover_soft_deleted_key_vaults = true
    }
    resource_group {
      prevent_deletion_if_contains_resources = true
    }
  }
}

provider "azuread" {
  tenant_id   = var.azure.tenant_id
  environment = var.azure_cloud == "AzureUSGovernment" ? "usgovernment" : "global"
}

provider "azapi" {
  subscription_id = var.azure.subscription_id
  tenant_id       = var.azure.tenant_id
  environment     = var.azure_cloud == "AzureUSGovernment" ? "usgovernment" : "public"
}
