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

# Random string for uniqueness
resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

# Resource Group
resource "azurerm_resource_group" "this" {
  name     = var.resource_group_name != "" ? var.resource_group_name : "rg-snapshot-cleanup-${random_string.suffix.result}"
  location = var.location
  tags     = var.tags
}

# Storage Account for Function App and reports
resource "azurerm_storage_account" "this" {
  name                     = "st${random_string.suffix.result}"
  resource_group_name      = azurerm_resource_group.this.name
  location                 = azurerm_resource_group.this.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  tags                     = var.tags
}

# Storage container for reports
resource "azurerm_storage_container" "reports" {
  name                  = var.storage_container_name
  storage_account_name  = azurerm_storage_account.this.name
  container_access_type = "private"
}

# App Service Plan
resource "azurerm_service_plan" "this" {
  name                = "plan-snapshot-cleanup-${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  os_type             = "Linux"
  sku_name            = var.app_service_sku
  tags                = var.tags
}

# Application Insights
resource "azurerm_application_insights" "this" {
  name                = "ai-snapshot-cleanup-${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  application_type    = "web"
  tags                = var.tags
}

# User Assigned Managed Identity
resource "azurerm_user_assigned_identity" "this" {
  name                = "id-snapshot-cleanup-${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  tags                = var.tags
}

# Function App
resource "azurerm_linux_function_app" "this" {
  name                       = "func-snapshot-cleanup-${random_string.suffix.result}"
  resource_group_name        = azurerm_resource_group.this.name
  location                   = azurerm_resource_group.this.location
  storage_account_name       = azurerm_storage_account.this.name
  storage_account_access_key = azurerm_storage_account.this.primary_access_key
  service_plan_id            = azurerm_service_plan.this.id
  
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.this.id]
  }
  
  app_settings = {
    "FUNCTIONS_WORKER_RUNTIME"       = "python"
    "APPINSIGHTS_INSTRUMENTATIONKEY" = azurerm_application_insights.this.instrumentation_key
    "MANAGED_IDENTITY_CLIENT_ID"     = azurerm_user_assigned_identity.this.client_id
    "SUBSCRIPTION_ID"                = var.specific_subscription_id
    "ENABLE_DELETION"                = var.enable_deletion
    "DRY_RUN"                        = var.dry_run
    "LOG_LEVEL"                      = var.log_level
    "STORAGE_CONNECTION_STRING"      = azurerm_storage_account.this.primary_connection_string
    "STORAGE_CONTAINER_NAME"         = azurerm_storage_container.this.name
    "SCHEDULE"                       = var.schedule_expression
  }
  
  site_config {
    application_stack {
      python_version = "3.9"
    }
    application_insights_connection_string = azurerm_application_insights.this.connection_string
    application_insights_key               = azurerm_application_insights.this.instrumentation_key
  }
  
  tags = var.tags
}

# Deploy the function code
resource "azurerm_function_app_function" "snapshot_cleanup" {
  name            = "SnapshotCleanup"
  function_app_id = azurerm_linux_function_app.this.id
  
  config_json = jsonencode({
    "bindings" = [
      {
        "authLevel" = "function"
        "direction" = "in"
        "methods"   = ["get", "post"]
        "name"      = "req"
        "type"      = "httpTrigger"
      },
      {
        "direction" = "out"
        "name"      = "$return"
        "type"      = "http"
      },
      {
        "direction" = "in"
        "name"      = "timer"
        "schedule"  = var.schedule_expression
        "type"      = "timerTrigger"
      }
    ]
  })
}

# Role assignments for the managed identity
resource "azurerm_role_assignment" "snapshot_reader" {
  count                = var.specific_subscription_id != "" ? 1 : 0
  scope                = "/subscriptions/${var.specific_subscription_id}"
  role_definition_name = "Reader"
  principal_id         = azurerm_user_assigned_identity.this.principal_id
}

resource "azurerm_role_assignment" "snapshot_contributor" {
  count                = var.specific_subscription_id != "" && var.enable_deletion ? 1 : 0
  scope                = "/subscriptions/${var.specific_subscription_id}"
  role_definition_name = "Storage Account Contributor"
  principal_id         = azurerm_user_assigned_identity.this.principal_id
}

# Custom role for snapshot management if needed
resource "azurerm_role_definition" "snapshot_manager" {
  count       = var.create_custom_role ? 1 : 0
  name        = "Snapshot Cleanup Manager"
  scope       = var.specific_subscription_id != "" ? "/subscriptions/${var.specific_subscription_id}" : data.azurerm_subscription.current.id
  description = "Custom role for managing orphaned snapshots"

  permissions {
    actions = [
      "Microsoft.Compute/snapshots/read",
      "Microsoft.Compute/snapshots/write",
      "Microsoft.Compute/snapshots/delete",
      "Microsoft.Compute/disks/read",
      "Microsoft.Resources/subscriptions/resourceGroups/read"
    ]
    not_actions = []
  }

  assignable_scopes = [
    var.specific_subscription_id != "" ? "/subscriptions/${var.specific_subscription_id}" : data.azurerm_subscription.current.id
  ]
}

# Data source for current subscription
data "azurerm_subscription" "current" {}
