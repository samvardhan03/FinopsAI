# Azure Snapshot Cleanup Tool - Usage Guide

This guide provides detailed instructions for using the Azure Snapshot Cleanup Tool to identify and manage orphaned snapshots.

## Table of Contents
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Basic Usage](#basic-usage)
- [Authentication Methods](#authentication-methods)
- [Command-Line Options](#command-line-options)
- [Example Scenarios](#example-scenarios)
- [Troubleshooting](#troubleshooting)

## Prerequisites

Before using the tool, ensure you have the following:

1. **Python 3.6+**: The tool requires Python 3.6 or newer.
2. **Azure CLI** (recommended): For CLI-based authentication.
3. **Appropriate Azure permissions**: The account used needs:
   - `Microsoft.Compute/snapshots/read` permission to list and read snapshots
   - `Microsoft.Compute/disks/read` permission to verify disk existence
   - `Microsoft.Compute/snapshots/delete` permission (only if you plan to delete snapshots)
   - `Microsoft.Resources/subscriptions/read` permission to list subscriptions

## Installation

### Option 1: Using setup scripts

1. Clone or download the repository:
   ```bash
   git clone https://github.com/your-org/azure-snapshot-cleanup.git
   cd azure-snapshot-cleanup
   ```

2. Run the appropriate setup script:
   - On Linux/Mac:
     ```bash
     ./setup.sh
     ```
   - On Windows:
     ```
     setup.bat
     ```

### Option 2: Manual setup

1. Clone or download the repository.
2. Create a virtual environment:
   ```bash
   python -m venv venv
   ```
3. Activate the virtual environment:
   - On Linux/Mac:
     ```bash
     source venv/bin/activate
     ```
   - On Windows:
     ```
     venv\Scripts\activate.bat
     ```
4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Basic Usage

### Python Script

The primary tool is the Python script which provides the most functionality:

```bash
# Scan for orphaned snapshots (dry run mode)
python scripts/azure_snapshot_cleanup.py --auth-method cli --dry-run

# Scan a specific subscription
python scripts/azure_snapshot_cleanup.py --auth-method cli --subscription-id "00000000-0000-0000-0000-000000000000" --dry-run

# Export results to JSON
python scripts/azure_snapshot_cleanup.py --auth-method cli --export results.json

# Delete orphaned snapshots (CAUTION!)
python scripts/azure_snapshot_cleanup.py --auth-method cli --delete
```

### Bash Script (Linux/Mac)

For Linux/Mac users, a Bash script is also available:

```bash
# Scan for orphaned snapshots (dry run mode)
./scripts/azure_snapshot_cleanup.sh --verbose

# Scan a specific subscription
./scripts/azure_snapshot_cleanup.sh -s "00000000-0000-0000-0000-000000000000" --verbose

# Export results to JSON
./scripts/azure_snapshot_cleanup.sh -e results.json

# Delete orphaned snapshots (CAUTION!)
./scripts/azure_snapshot_cleanup.sh --delete --no-dry-run
```

## Authentication Methods

The tool supports multiple authentication methods:

### 1. Azure CLI Authentication

This uses your existing Azure CLI login:

```bash
python scripts/azure_snapshot_cleanup.py --auth-method cli
```

Prerequisites:
- Azure CLI installed
- Already logged in with `az login`

### 2. Managed Identity Authentication

For use in Azure-hosted environments (VMs, App Services, etc.):

```bash
python scripts/azure_snapshot_cleanup.py --auth-method managed-identity
```

Prerequisites:
- Running on an Azure resource with a managed identity assigned
- Identity has appropriate permissions

### 3. Service Principal Authentication

For automated scripts and CI/CD pipelines:

```bash
python scripts/azure_snapshot_cleanup.py --auth-method service-principal \
    --sp-client-id "YOUR_CLIENT_ID" \
    --sp-client-secret "YOUR_CLIENT_SECRET" \
    --sp-tenant-id "YOUR_TENANT_ID"
```

Prerequisites:
- Service principal created in Azure AD
- Service principal has appropriate permissions

## Command-Line Options

### Python Script Options

```
--auth-method {cli,managed-identity,service-principal}
                      Authentication method (default: cli)
--sp-client-id SP_CLIENT_ID
                      Service Principal Client ID
--sp-client-secret SP_CLIENT_SECRET
                      Service Principal Client Secret
--sp-tenant-id SP_TENANT_ID
                      Service Principal Tenant ID
--subscription-id SUBSCRIPTION_ID
                      Specific subscription ID to scan
--delete              Delete orphaned snapshots (default: report only)
--dry-run             Perform a dry run (don't actually delete snapshots)
--export EXPORT       Export results to a JSON file
--log-level {DEBUG,INFO,WARNING,ERROR}
                      Set logging level (default: INFO)
```

### Bash Script Options

```
-h, --help                 Show this help message
-s, --subscription ID      Specific subscription ID to scan
-d, --delete               Delete orphaned snapshots (default: report only)
--no-dry-run               Actually perform deletions (default: dry run)
-e, --export FILE          Export results to a JSON file
-l, --log FILE             Log file (default: snapshot_cleanup_<timestamp>.log)
-v, --verbose              Enable verbose output
```

## Example Scenarios

### Scenario 1: Regular Audit

Regular audit of all subscriptions to identify potential orphaned snapshots:

```bash
python scripts/azure_snapshot_cleanup.py --dry-run --export audit_results.json
```

This will:
- Scan all accessible subscriptions
- Identify orphaned snapshots
- Export results to a JSON file
- Not delete any snapshots

### Scenario 2: Cleanup with Verification

A two-step process to verify and then clean up:

1. First, scan and export:
   ```bash
   python scripts/azure_snapshot_cleanup.py --dry-run --export cleanup_candidates.json
   ```

2. Review the JSON file to verify the snapshots should be deleted.

3. Then perform the actual deletion:
   ```bash
   python scripts/azure_snapshot_cleanup.py --delete
   ```

### Scenario 3: Automated Cleanup Job

For automated jobs (e.g., scheduled tasks):

```bash
python scripts/azure_snapshot_cleanup.py --auth-method service-principal \
    --sp-client-id "$SP_CLIENT_ID" \
    --sp-client-secret "$SP_CLIENT_SECRET" \
    --sp-tenant-id "$SP_TENANT_ID" \
    --delete --log-level INFO
```

## Troubleshooting

### Common Issues

1. **Authentication Errors**:
   - Ensure you're properly logged in with `az login` when using CLI authentication
   - Verify service principal credentials and permissions
   - For managed identity, ensure the identity is correctly assigned

2. **Permission Issues**:
   - Verify that your account has the necessary permissions for all operations
   - For multi-subscription scans, ensure you have access to all target subscriptions

3. **No Snapshots Found**:
   - Check if you're scanning the correct subscription(s)
   - Verify that snapshots exist in the target subscription(s)

### Logging

The tool logs information to help with troubleshooting:

- Use `--log-level DEBUG` for more detailed logs
- Check the log file if using the Bash script version (default: `snapshot_cleanup_<timestamp>.log`)

### Getting Help

If you encounter issues:

1. Check the logs for detailed error messages
2. Refer to the `docs/troubleshooting.md` file for common issues
3. Create an issue in the GitHub repository with details of your problem
