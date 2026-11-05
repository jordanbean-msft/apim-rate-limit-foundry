terraform {
  required_providers {
    azurerm  = { source = "hashicorp/azurerm", version = "~> 5.13" }
    azuread  = { source = "hashicorp/azuread", version = "~> 3.10" }
    time     = { source = "hashicorp/time", version = "~> 0.14" }
    azurecaf = { source = "aztfmod/azurecaf", version = "~> 1.2" }
  }
}
