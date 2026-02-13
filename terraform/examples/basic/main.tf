terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">=3.0.0"
    }
  }
}

provider "azurerm" {
  features {}
}

module "snapshot_cleanup" {
  source = "../../modules/snapshot-cleanup"

  # Basic configuration
  resource_group_name    = var.resource_group_name
  location               = var.location
  tags                   = var.tags
  
  # App and execution configuration
  app_service_sku        = "B1"  # Basic tier, sufficient for most use cases
  specific_subscription_id = var.subscription_id
  enable_deletion        = false
  dry_run                = true
  log_level              = "INFO"
  
  # Schedule (daily at 1 AM)
  schedule_expression    = "0 0 1 * * *"
}

# Outputs
output "function_app_url" {
  description = "URL of the deployed Function App"
  value       = module.snapshot_cleanup.function_app_url
}

output "resource_group_name" {
  description = "Name of the resource group"
  value       = module.snapshot_cleanup.resource_group_name
}
