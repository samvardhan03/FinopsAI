# Azure Snapshot Cleanup - Troubleshooting Guide

This document provides solutions for common issues encountered when using the Azure Snapshot Cleanup tool.

## Table of Contents
- [Authentication Issues](#authentication-issues)
- [Permission Problems](#permission-problems)
- [Resource Discovery Issues](#resource-discovery-issues)
- [Deletion Failures](#deletion-failures)
- [Performance Concerns](#performance-concerns)
- [Error Messages](#common-error-messages)
- [Logging and Debugging](#logging-and-debugging)

## Authentication Issues

### Azure CLI Authentication Failures

**Issue**: Unable to authenticate using CLI method.

**Solutions**:
1. Ensure you're logged in with `az login` before running the tool
2. Verify your login session hasn't expired with `az account show`
3. If you have multiple tenants, specify the tenant with `az login --tenant <tenant-id>`
4. Try clearing your Azure CLI token cache:
   ```bash
   rm -rf ~/.azure/msal_token_cache.json
   az login
   ```

### Managed Identity Authentication Failures

**Issue**: Tool fails when using managed identity authentication.

**Solutions**:
1. Verify the Azure resource (VM, App Service, etc.) has a managed identity assigned
2. Check that the identity has appropriate permissions in all target subscriptions
3. If using a user-assigned managed identity, ensure the `MANAGED_IDENTITY_CLIENT_ID` environment variable is correctly set
4. For debugging, try running this command on the Azure resource:
   ```bash
   curl 'http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fmanagement.azure.com%2F' -H Metadata:true
   ```

### Service Principal Authentication Failures

**Issue**: Unable to authenticate with service principal credentials.

**Solutions**:
1. Verify client ID, client secret, and tenant ID are correct
2. Ensure the service principal hasn't expired or been disabled
3. Check if the client secret has expired and needs to be renewed
4. Verify the service principal has appropriate role assignments in Azure RBAC

## Permission Problems

### Insufficient Permissions

**Issue**: Tool fails with "Unauthorized" or permission-related errors.

**Solutions**:
1. Ensure the authenticated identity has the following permissions:
   - `Microsoft.Compute/snapshots/read`
   - `Microsoft.Compute/disks/read`
   - `Microsoft.Compute/snapshots/delete` (if deleting snapshots)
   - `Microsoft.Resources/subscriptions/read`
2. Assign the built-in "Reader" role at the subscription level for scanning
3. Assign the built-in "Storage Account Contributor" role for deletion operations
4. Check if there are Azure Policy restrictions in place that might be blocking operations

### Multi-Subscription Access Issues

**Issue**: Can access some subscriptions but not others.

**Solutions**:
1. Verify the identity has appropriate permissions in all target subscriptions
2. Check if you're being blocked by Azure Policy restrictions
3. Try specifying a single subscription ID with `--subscription-id` to isolate the issue
4. For service principals, ensure they have been granted access to each subscription

## Resource Discovery Issues

### No Snapshots Found

**Issue**: Tool reports zero snapshots when you know they exist.

**Solutions**:
1. Verify you're scanning the correct subscription(s)
2. Check if snapshots are in a resource group with restricted access
3. Ensure there are no filters applied through the script parameters
4. Try running with `--log-level DEBUG` to see detailed discovery information
5. Manually verify snapshot existence with:
   ```bash
   az snapshot list --subscription <subscription-id> --query "[].name" -o tsv
   ```

### False Positives (Incorrectly Identified as Orphaned)

**Issue**: Tool identifies snapshots as orphaned when their source disks actually exist.

**Solutions**:
1. Verify the tool can access the source disk's subscription
2. Check for permission issues that might prevent reading the source disk
3. If the source disk is in another subscription, ensure you have access to that subscription
4. Run with `--log-level DEBUG` to see the detailed disk verification logic

## Deletion Failures

### Failed Deletions

**Issue**: Tool reports failures when trying to delete snapshots.

**Solutions**:
1. Verify the identity has `Microsoft.Compute/snapshots/delete` permission
2. Check if the snapshots are locked with Azure Resource Manager locks
3. Investigate if there are Azure Policies preventing deletion
4. Look for snapshot dependencies (though this should be rare)
5. For service principals, ensure the "User Access Administrator" role is assigned if needed

### Snapshot Lock Issues

**Issue**: Deletions fail due to resource locks.

**Solutions**:
1. Check for resource locks at the snapshot, resource group, or subscription level:
   ```bash
   az lock list --resource-group <resource-group-name> --resource-name <snapshot-name> --resource-type Microsoft.Compute/snapshots
   ```
2. Remove locks if appropriate (requires Owner or User Access Administrator role):
   ```bash
   az lock delete --name <lock-name> --resource-group <resource-group-name>
   ```

## Performance Concerns

### Tool Runs Slowly

**Issue**: The tool takes a long time to scan large environments.

**Solutions**:
1. Specify a single subscription with `--subscription-id` to reduce scope
2. For Python script, ensure your environment has good network connectivity to Azure
3. Try the parallel processing option (if available in your version)
4. For environments with thousands of snapshots, consider running the tool during off-hours

### High Memory Usage

**Issue**: Tool consumes excessive memory on large environments.

**Solutions**:
1. Scan one subscription at a time
2. Ensure you're using the latest version which may have optimized memory handling
3. Increase available memory if running in a constrained environment

## Common Error Messages

### "ResourceNotFound"

**Error**: `The Resource 'Microsoft.Compute/snapshots/[name]' under resource group '[group]' was not found.`

**Solutions**:
1. The snapshot may have been deleted already
2. Check if you're using the correct resource group and snapshot name
3. Verify subscription context is correct

### "AuthorizationFailed"

**Error**: `The client '[client]' with object id '[id]' does not have authorization to perform action 'Microsoft.Compute/snapshots/read'`

**Solutions**:
1. Assign appropriate RBAC roles as described in the Permission Problems section
2. Verify the identity's permissions in the Azure portal
3. For managed identities, ensure the identity is properly configured

### "Invalid resource ID"

**Error**: `Parameter 'resource_id' with value '[value]' is not a valid resource ID.`

**Solutions**:
1. This typically happens with malformed resource IDs in snapshots
2. Use `--log-level DEBUG` to see the problematic resource ID
3. You may need to handle these snapshots separately

## Logging and Debugging

### Enabling Detailed Logs

To get more information for troubleshooting:

1. Use the `--log-level DEBUG` option with the Python script:
   ```bash
   python scripts/azure_snapshot_cleanup.py --log-level DEBUG --dry-run
   ```

2. Use the `--verbose` option with the Bash script:
   ```bash
   ./scripts/azure_snapshot_cleanup.sh --verbose
   ```

### Interpreting Logs

Key log messages to look for:

- Authentication messages: Look for "Using [method] authentication"
- Subscription access: Check "Found [number] accessible subscription(s)"
- Snapshot discovery: See "Found [number] snapshots in subscription"
- Disk verification: Look for "Disk exists: [name]" or "Disk does not exist: [name]"
- Deletion operations: Check for "Successfully deleted snapshot" or "Failed to delete snapshot"

### Collecting Logs for Support

If you need to share logs for support purposes:

1. For Python script:
   ```bash
   python scripts/azure_snapshot_cleanup.py --log-level DEBUG > cleanup_debug.log 2>&1
   ```

2. For Bash script:
   ```bash
   ./scripts/azure_snapshot_cleanup.sh --verbose --log detailed_log.txt
   ```

## Additional Help

If you continue to experience issues after trying these troubleshooting steps:

1. Check for known issues in the project's GitHub repository
2. Update to the latest version of the tool
3. Open an issue on the GitHub repository with:
   - Tool version
   - Command line used
   - Error messages (with sensitive information redacted)
   - Log output with `--log-level DEBUG` or `--verbose` option
