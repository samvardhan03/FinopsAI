variable "resource_group_name" {
  description = "Name of the resource group to create resources in"
  type        = string
  default     = ""
}

variable "location" {
  description = "Azure region to deploy resources to"
  type        = string
  default     = "eastus"
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}

variable "app_service_sku" {
  description = "SKU for the App Service Plan"
  type        = string
  default     = "B1"
}

variable "specific_subscription_id" {
  description = "Specific subscription ID to scan (empty means scan all accessible)"
  type        = string
  default     = ""
}

variable "enable_deletion" {
  description = "Enable deletion of orphaned snapshots"
  type        = bool
  default     = false
}

variable "dry_run" {
  description = "Perform a dry run (don't actually delete snapshots)"
  type        = bool
  default     = true
}

variable "log_level" {
  description = "Logging level for the function"
  type        = string
  default     = "INFO"
  validation {
    condition     = contains(["DEBUG", "INFO", "WARNING", "ERROR"], var.log_level)
    error_message = "Log level must be one of: DEBUG, INFO, WARNING, ERROR."
  }
}

variable "storage_container_name" {
  description = "Name of the storage container to store reports"
  type        = string
  default     = "snapshot-reports"
}

variable "schedule_expression" {
  description = "CRON expression for scheduled execution"
  type        = string
  default     = "0 0 0 * * *"  # Daily at midnight
}

variable "create_custom_role" {
  description = "Create a custom role for snapshot management"
  type        = bool
  default     = false
}
