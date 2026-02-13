
set -e

# Default values
SPECIFIC_SUBSCRIPTION=""
LOG_FILE="snapshot_cleanup_$(date +%Y%m%d_%H%M%S).log"
EXPORT_FILE=""
DRY_RUN=true
DELETE_MODE=false
VERBOSE=false

# Function to show usage
show_usage() {
  cat << EOF
Azure Snapshot Cleanup Tool

Usage: $(basename "$0") [options]

Options:
  -h, --help                 Show this help message
  -s, --subscription ID      Specific subscription ID to scan
  -d, --delete               Delete orphaned snapshots (default: report only)
  --no-dry-run               Actually perform deletions (default: dry run)
  -e, --export FILE          Export results to a JSON file
  -l, --log FILE             Log file (default: snapshot_cleanup_<timestamp>.log)
  -v, --verbose              Enable verbose output

Example:
  $(basename "$0") --subscription 00000000-0000-0000-0000-000000000000 --export results.json
  $(basename "$0") --delete --no-dry-run  # WARNING: This will delete snapshots!

EOF
  exit 1
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      show_usage
      ;;
    -s|--subscription)
      SPECIFIC_SUBSCRIPTION="$2"
      shift 2
      ;;
    -d|--delete)
      DELETE_MODE=true
      shift
      ;;
    --no-dry-run)
      DRY_RUN=false
      shift
      ;;
    -e|--export)
      EXPORT_FILE="$2"
      shift 2
      ;;
    -l|--log)
      LOG_FILE="$2"
      shift 2
      ;;
    -v|--verbose)
      VERBOSE=true
      shift
      ;;
    *)
      echo "Unknown option: $1"
      show_usage
      ;;
  esac
done

# Setup logging
log() {
  local level="$1"
  local message="$2"
  local timestamp=$(date +"%Y-%m-%d %H:%M:%S")
  echo "[$timestamp] [$level] $message" | tee -a "$LOG_FILE"
}

info() {
  log "INFO" "$1"
}

error() {
  log "ERROR" "$1"
}

debug() {
  if [[ "$VERBOSE" == "true" ]]; then
    log "DEBUG" "$1"
  fi
}

# Check dependencies
check_dependencies() {
  if ! command -v az &> /dev/null; then
    error "Azure CLI (az) is not installed. Please install it first."
    exit 1
  fi
  
  if ! command -v jq &> /dev/null; then
    error "jq is not installed. Please install it first."
    exit 1
  fi
  
  # Check if logged in to Azure
  if ! az account show &> /dev/null; then
    error "Not logged in to Azure. Please run 'az login' first."
    exit 1
  fi
}

# Get subscriptions to scan
get_subscriptions() {
  local subscriptions
  
  if [[ -n "$SPECIFIC_SUBSCRIPTION" ]]; then
    info "Using specific subscription: $SPECIFIC_SUBSCRIPTION"
    subscriptions=$(az account show --subscription "$SPECIFIC_SUBSCRIPTION" --output json) || {
      error "Failed to get subscription details for $SPECIFIC_SUBSCRIPTION"
      exit 1
    }
  else
    info "Getting list of accessible subscriptions"
    subscriptions=$(az account list --output json) || {
      error "Failed to get subscription list"
      exit 1
    }
  fi
  
  echo "$subscriptions"
}

# Check if a disk exists
disk_exists() {
  local subscription_id="$1"
  local source_disk_id="$2"
  
  # Parse the resource ID to extract resource group and disk name
  # Format: /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Compute/disks/{name}
  local parts=(${source_disk_id//\// })
  
  # Check if this ID format is valid for a disk
  if [[ ${#parts[@]} -lt 9 || "${parts[6]}" != "Microsoft.Compute" || "${parts[7]}" != "disks" ]]; then
    debug "Invalid disk resource ID format: $source_disk_id"
    return 1
  fi
  
  local resource_group="${parts[4]}"
  local disk_name="${parts[8]}"
  
  debug "Checking if disk exists: $disk_name in $resource_group"
  
  # Try to get the disk
  if az disk show --subscription "$subscription_id" -g "$resource_group" -n "$disk_name" --query id -o tsv &> /dev/null; then
    debug "Disk exists: $disk_name"
    return 0
  else
    debug "Disk does not exist: $disk_name"
    return 1
  fi
}

# Find orphaned snapshots
find_orphaned_snapshots() {
  local subscriptions="$1"
  local orphaned_snapshots=()
  local total_count=0
  
  # Process each subscription
  echo "$subscriptions" | jq -c '.[] | {id: .id, name: .name}' | while read -r subscription; do
    local sub_id=$(echo "$subscription" | jq -r '.id')
    local sub_name=$(echo "$subscription" | jq -r '.name')
    
    info "Scanning snapshots in subscription: $sub_name ($sub_id)"
    
    # Get all snapshots in the subscription
    local snapshots
    snapshots=$(az snapshot list --subscription "$sub_id" --output json) || {
      error "Failed to list snapshots in subscription $sub_id"
      continue
    }
    
    local snapshot_count=$(echo "$snapshots" | jq length)
    info "Found $snapshot_count snapshots in subscription"
    
    # Check each snapshot
    echo "$snapshots" | jq -c '.[]' | while read -r snapshot; do
      local name=$(echo "$snapshot" | jq -r '.name')
      local id=$(echo "$snapshot" | jq -r '.id')
      local resource_group=$(echo "$id" | cut -d'/' -f5)
      local source_disk_id=$(echo "$snapshot" | jq -r '.creationData.sourceResourceId // empty')
      
      # Skip if no source disk ID
      if [[ -z "$source_disk_id" ]]; then
        debug "Snapshot $name has no source disk ID, skipping"
        continue
      fi
      
      # Check if source disk exists
      if ! disk_exists "$sub_id" "$source_disk_id"; then
        local size_gb=$(echo "$snapshot" | jq -r '.diskSizeGb // 0')
        local created_time=$(echo "$snapshot" | jq -r '.timeCreated // "Unknown"')
        local tags=$(echo "$snapshot" | jq -r '.tags // {}')
        
        info "Found orphaned snapshot: $name ($size_gb GB) in $resource_group"
        
        # Add to orphaned snapshots array
        local orphaned_snapshot=$(cat <<EOF
{
  "subscription_id": "$sub_id",
  "subscription_name": "$sub_name",
  "resource_group": "$resource_group",
  "name": "$name",
  "id": "$id",
  "source_disk_id": "$source_disk_id",
  "size_gb": $size_gb,
  "created_time": "$created_time",
  "tags": $tags
}
EOF
)
        orphaned_snapshots+=("$orphaned_snapshot")
        ((total_count++))
      fi
    done
  done
  
  info "Found $total_count orphaned snapshots across all subscriptions"
  
  # Return the orphaned snapshots as JSON array
  if [[ ${#orphaned_snapshots[@]} -eq 0 ]]; then
    echo "[]"
  else
    local json_array="["
    for ((i=0; i<${#orphaned_snapshots[@]}; i++)); do
      if [[ $i -gt 0 ]]; then
        json_array+=","
      fi
      json_array+="${orphaned_snapshots[$i]}"
    done
    json_array+="]"
    echo "$json_array"
  fi
}

# Delete orphaned snapshots
delete_orphaned_snapshots() {
  local orphaned_snapshots="$1"
  local successful=0
  local failed=0
  
  echo "$orphaned_snapshots" | jq -c '.[]' | while read -r snapshot; do
    local sub_id=$(echo "$snapshot" | jq -r '.subscription_id')
    local resource_group=$(echo "$snapshot" | jq -r '.resource_group')
    local name=$(echo "$snapshot" | jq -r '.name')
    
    if [[ "$DRY_RUN" == "true" ]]; then
      info "DRY RUN: Would delete snapshot $name in $resource_group"
      ((successful++))
    else
      info "Deleting snapshot $name in $resource_group"
      
      if az snapshot delete --subscription "$sub_id" -g "$resource_group" -n "$name" --yes &> /dev/null; then
        info "Successfully deleted snapshot $name"
        ((successful++))
      else
        error "Failed to delete snapshot $name"
        ((failed++))
      fi
    fi
  done
  
  echo "{\"successful\": $successful, \"failed\": $failed}"
}

# Export results to JSON file
export_to_json() {
  local orphaned_snapshots="$1"
  local file_path="$2"
  
  if [[ "$(echo "$orphaned_snapshots" | jq length)" -eq 0 ]]; then
    info "No orphaned snapshots to export"
    return
  }
  
  local json_output=$(cat <<EOF
{
  "generated_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "orphaned_snapshots": $orphaned_snapshots
}
EOF
)
  
  echo "$json_output" > "$file_path"
  info "Exported $(echo "$orphaned_snapshots" | jq length) orphaned snapshots to $file_path"
}

# Print summary of orphaned snapshots
print_summary() {
  local orphaned_snapshots="$1"
  
  local count=$(echo "$orphaned_snapshots" | jq length)
  
  if [[ $count -eq 0 ]]; then
    info "No orphaned snapshots found"
    return
  }
  
  local total_size=$(echo "$orphaned_snapshots" | jq 'map(.size_gb) | add')
  
  echo ""
  echo "=== Orphaned Snapshots Summary ==="
  echo "Total orphaned snapshots: $count"
  echo "Total size: $total_size GB"
  
  echo ""
  echo "Breakdown by subscription:"
  
  # Group by subscription and print stats
  echo "$orphaned_snapshots" | jq -r '.[] | .subscription_name' | sort | uniq | while read -r sub_name; do
    local sub_snapshots=$(echo "$orphaned_snapshots" | jq -c "[.[] | select(.subscription_name == \"$sub_name\")]")
    local sub_count=$(echo "$sub_snapshots" | jq length)
    local sub_size=$(echo "$sub_snapshots" | jq 'map(.size_gb) | add')
    
    echo "  - $sub_name: $sub_count snapshots, $sub_size GB"
  done
}

# Print details of orphaned snapshots
print_snapshots() {
  local orphaned_snapshots="$1"
  
  local count=$(echo "$orphaned_snapshots" | jq length)
  
  if [[ $count -eq 0 ]]; then
    return
  }
  
  echo ""
  echo "Orphaned Snapshots:"
  echo "-------------------"
  
  local format="%-40s %-20s %-10s %-25s\n"
  printf "$format" "SNAPSHOT NAME" "RESOURCE GROUP" "SIZE (GB)" "CREATED TIME"
  printf "$format" "------------" "--------------" "--------" "------------"
  
  echo "$orphaned_snapshots" | jq -c '.[]' | while read -r snapshot; do
    local name=$(echo "$snapshot" | jq -r '.name')
    local rg=$(echo "$snapshot" | jq -r '.resource_group')
    local size=$(echo "$snapshot" | jq -r '.size_gb')
    local created=$(echo "$snapshot" | jq -r '.created_time')
    
    printf "$format" "$name" "$rg" "$size" "$created"
  done
}

# Main function
main() {
  # Check dependencies
  check_dependencies
  
  info "Azure Snapshot Cleanup Tool started"
  
  # Get subscriptions to scan
  local subscriptions
  subscriptions=$(get_subscriptions)
  
  # Find orphaned snapshots
  info "Finding orphaned snapshots..."
  local orphaned_snapshots
  orphaned_snapshots=$(find_orphaned_snapshots "$subscriptions")
  
  # Print summary and details
  print_summary "$orphaned_snapshots"
  print_snapshots "$orphaned_snapshots"
  
  # Export to JSON if requested
  if [[ -n "$EXPORT_FILE" ]]; then
    export_to_json "$orphaned_snapshots" "$EXPORT_FILE"
  fi
  
  # Delete orphaned snapshots if requested
  if [[ "$DELETE_MODE" == "true" || "$DRY_RUN" == "true" ]]; then
    if [[ "$DELETE_MODE" == "true" && "$DRY_RUN" == "false" ]]; then
      echo ""
      echo "WARNING: This will delete orphaned snapshots."
      read -p "Continue? [y/N]: " confirmation
      
      if [[ "$confirmation" != "y" && "$confirmation" != "Y" ]]; then
        info "Deletion cancelled"
        exit 0
      fi
    fi
    
    echo ""
    info "Processing snapshots for deletion (dry run: $DRY_RUN)..."
    local delete_results
    delete_results=$(delete_orphaned_snapshots "$orphaned_snapshots")
    
    local successful=$(echo "$delete_results" | jq -r '.successful')
    local failed=$(echo "$delete_results" | jq -r '.failed')
    
    echo ""
    echo "=== Deletion Results ==="
    echo "Successful: $successful"
    echo "Failed: $failed"
  fi
  
  info "Azure Snapshot Cleanup Tool finished"
}

# Run main function
main