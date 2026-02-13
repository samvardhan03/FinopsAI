output "function_app_name" {
  description = "Name of the deployed Function App"
  value       = azurerm_linux_function_app.this.name
}

output "function_app_url" {
  description = "URL of the deployed Function App"
  value       = "https://${azurerm_linux_function_app.this.default_hostname}/api/SnapshotCleanup"
}

output "function_app_key" {
  description = "Default Function App key"
  value       = azurerm_linux_function_app.this.default_function_key
  sensitive   = true
}

output "resource_group_name" {
  description = "Name of the resource group containing all resources"
  value       = azurerm_resource_group.this.name
}

output "storage_account_name" {
  description = "Name of the storage account for reports"
  value       = azurerm_storage_account.this.name
}

output "storage_container_name" {
  description = "Name of the storage container for reports"
  value       = azurerm_storage_container.this.name
}

output "managed_identity_id" {
  description = "ID of the managed identity used by the Function App"
  value       = azurerm_user_assigned_identity.this.id
}

output "managed_identity_client_id" {
  description = "Client ID of the managed identity"
  value       = azurerm_user_assigned_identity.this.client_id
}

output "application_insights_name" {
  description = "Name of the Application Insights resource"
  value       = azurerm_application_insights.this.name
}

output "application_insights_instrumentation_key" {
  description = "Instrumentation key for Application Insights"
  value       = azurerm_application_insights.this.instrumentation_key
  sensitive   = true
}
