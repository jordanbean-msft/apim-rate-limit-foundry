terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    azurecaf = {
      source  = "aztfmod/azurecaf"
      version = "~> 1.2"
    }
  }

  # Backend configured by azd via infra/provider.conf.json (native Terraform remote state).
  # azd substitutes ${RS_*} and ${AZURE_ENV_NAME} placeholders at provision time.
  # Before running azd provision, set:
  #   azd env set RS_RESOURCE_GROUP <rg>
  #   azd env set RS_STORAGE_ACCOUNT <sa>
  #   azd env set RS_CONTAINER_NAME  <container>
  backend "azurerm" {}
}

provider "azurerm" {
  subscription_id     = var.azure.subscription_id
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
