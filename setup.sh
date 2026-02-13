#!/bin/bash

if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not found. Please install Python 3."
    exit 1
fi

# Check for Azure CLI installation
if ! command -v az &> /dev/null; then
    echo "Warning: Azure CLI is not installed. It's recommended for authentication."
    echo "Visit https://docs.microsoft.com/en-us/cli/azure/install-azure-cli for installation instructions."
fi

# Create virtual environment
echo "Creating Python virtual environment..."
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Make the script executable
chmod +x scripts/azure_snapshot_cleanup.sh
chmod +x scripts/azure_snapshot_cleanup.py

echo ""
echo "Setup complete! To use the tool:"
echo "1. Activate the virtual environment: source venv/bin/activate"
echo "2. Run the Python script: python scripts/azure_snapshot_cleanup.py --auth-method cli --dry-run"
echo "   or the Bash script: ./scripts/azure_snapshot_cleanup.sh --verbose"
echo ""
echo "For more information, see the README.md or docs/usage_guide.md"
